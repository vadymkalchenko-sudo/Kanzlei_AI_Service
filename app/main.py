"""
FastAPI Main Application
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import logging
import uuid
import asyncio

from app.config import settings
from app.services.email_processor import email_processor
from app.services.ai_extractor import ai_extractor
from app.services.django_client import django_client

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Kanzlei AI Service",
    description="KI-gestützter Service für automatisierte Aktenanlage",
    version="0.1.0",
    debug=settings.debug
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Kanzlei AI Service",
        "version": "0.1.0",
        "status": "running",
        "provider": settings.llm_provider
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "provider": settings.llm_provider,
        "backend_url": settings.backend_url
    }


def safe_get(obj, *path, default=""):
    """Safely navigate object attributes. Returns default (empty string) if None or missing."""
    current = obj
    for attr in path:
        if current is None:
            return default
        current = getattr(current, attr, None)
    return current if current is not None else default

async def process_email_background_task(job_id: str, email_content_bytes: bytes, filename: str):
    """
    Background task to process the email and create structures in Django
    """
    try:
        logger.info(f"Job {job_id}: Starting processing for {filename}")
        
        # 1. Parse Email
        email_content = await email_processor.process_eml(email_content_bytes)
        logger.info(f"Job {job_id}: Extracted email subject '{email_content.subject}'")

        # 2. Extract Data with AI
        # Gather attachments for multimodal analysis
        ai_attachments = []
        supported_types = ["image/jpeg", "image/png", "image/webp", "application/pdf"]
        
        for att in email_content.attachments:
            # Simple mime type check - can be improved
            is_supported = False
            mime = "application/octet-stream" 
            
            if att.filename.lower().endswith(('.jpg', '.jpeg')):
                mime = "image/jpeg"
                is_supported = True
            elif att.filename.lower().endswith('.png'):
                mime = "image/png"
                is_supported = True
            elif att.filename.lower().endswith('.webp'):
                mime = "image/webp"
                is_supported = True
            elif att.filename.lower().endswith('.pdf'):
                mime = "application/pdf"
                is_supported = True
                
            if is_supported:
                ai_attachments.append({
                    "mime_type": mime,
                    "data": att.content
                })
        
        # Combine subject + body
        full_text = f"Betreff: {email_content.subject}\n\n{email_content.body}"
        
        # Call AI with text AND images
        case_data = await ai_extractor.extract_case_data(full_text, attachments=ai_attachments)
        logger.info(f"Job {job_id}: AI Extraction complete (with {len(ai_attachments)} attachments)")

        # ... (Mappings remain same) ...

        # 3. Create Mandant
        ansprache = safe_get(case_data, 'mandant', 'anrede')
        if not ansprache or ansprache not in ["Herr", "Frau", "Firma"]:
            ansprache = "Herr"

        mandant_payload = {
            "vorname": safe_get(case_data, 'mandant', 'vorname'),
            "nachname": safe_get(case_data, 'mandant', 'nachname'),
            "ansprache": ansprache,
            "strasse": safe_get(case_data, 'mandant', 'adresse', 'strasse'),
            "hausnummer": safe_get(case_data, 'mandant', 'adresse', 'hausnummer'),
            "plz": safe_get(case_data, 'mandant', 'adresse', 'plz'),
            "stadt": safe_get(case_data, 'mandant', 'adresse', 'ort'),
            "ignore_conflicts": True 
        }

        # Optional fields: Add only if present to avoid validation errors (e.g. empty email string)
        email = safe_get(case_data, 'mandant', 'email')
        if email:
            mandant_payload["email"] = email

        telefon = safe_get(case_data, 'mandant', 'telefon')
        if telefon:
            mandant_payload["telefon"] = telefon
            
        mandant_resp = await django_client.create_mandant(mandant_payload)
        mandant_id = mandant_resp['mandant_id']
        logger.info(f"Job {job_id}: Created Mandant {mandant_id}")

        # 4. Lookup/Create Gegner
        gegner_name = safe_get(case_data, 'gegner_versicherung', 'name')
        if not gegner_name or not gegner_name.strip():
            gegner_name = "Unbekannte Versicherung"

        gegner_payload = {
            "name": gegner_name,
            "strasse": safe_get(case_data, 'gegner_versicherung', 'adresse', 'strasse'),
            "hausnummer": safe_get(case_data, 'gegner_versicherung', 'adresse', 'hausnummer'),
            "plz": safe_get(case_data, 'gegner_versicherung', 'adresse', 'plz'),
            "stadt": safe_get(case_data, 'gegner_versicherung', 'adresse', 'ort'),
            "ignore_conflicts": True
        }
        gegner_resp = await django_client.lookup_or_create_gegner(gegner_payload)
        gegner_id = gegner_resp['gegner_id']
        logger.info(f"Job {job_id}: Resolved Gegner {gegner_id}")

        # 5. Create Akte
        akte_payload = {
            "mandant": mandant_id,
            "gegner": gegner_id,
            "info_zusatz": {
                "betreff": safe_get(case_data, 'betreff'),
                "unfalldatum": safe_get(case_data, 'unfall', 'datum'),
                "unfallort": safe_get(case_data, 'unfall', 'ort'),
                "kennzeichen_gegner": safe_get(case_data, 'unfall', 'kennzeichen_gegner'),
                "kennzeichen_mandant": safe_get(case_data, 'unfall', 'kennzeichen_mandant'),
                "weitere_kennzeichen": safe_get(case_data, 'unfall', 'weitere_kennzeichen', default=[]),
                "versicherungsnummer": safe_get(case_data, 'gegner_versicherung', 'schadennummer'),
                "zusammenfassung": safe_get(case_data, 'zusammenfassung')
            },
            "fragebogen_data": {
                # Mapping auf flache Frontend-Struktur (FragebogenData interface)
                "datum_zeit": safe_get(case_data, 'unfall', 'datum'),
                "unfallort": safe_get(case_data, 'unfall', 'ort'),
                "kfz_kennzeichen": safe_get(case_data, 'unfall', 'kennzeichen_mandant'),
                
                "vers_gegner": safe_get(case_data, 'gegner_versicherung', 'name'),
                "gegner_kfz": safe_get(case_data, 'unfall', 'kennzeichen_gegner'),
                "schaden_nr": safe_get(case_data, 'gegner_versicherung', 'schadennummer'),
                
                # Neue Fahrzeugdaten
                "kfz_typ": safe_get(case_data, 'fahrzeug', 'typ'),
                "kfz_kw_ps": safe_get(case_data, 'fahrzeug', 'kw'),
                "kfz_ez": safe_get(case_data, 'fahrzeug', 'ez'),
                
                # Defaults
                "polizei": False,
                "zeugen": False
            }
        }
        akte_resp = await django_client.create_akte(akte_payload)
        akte_id = akte_resp['akte_id']
        logger.info(f"Job {job_id}: Created Akte {akte_id} ({akte_resp.get('aktenzeichen')})")

        # 6. Upload Original Email
        # Use the bytes we read earlier
        await django_client.upload_dokument(
            akte_id=akte_id, 
            file_content=email_content_bytes, 
            filename=filename or "email.eml",
            titel="Original E-Mail"
        )
        logger.info(f"Job {job_id}: Uploaded email file")
        
        # 7. Upload Attachments
        for att in email_content.attachments:
            await django_client.upload_dokument(
                akte_id=akte_id, 
                file_content=att.content, 
                filename=att.filename,
                titel=att.filename
            )
            logger.info(f"Job {job_id}: Uploaded attachment {att.filename}")

        # 8. Create Ticket
        import datetime
        ticket_payload = {
            "akte": akte_id,
            "titel": "KI: Neue Akte aus E-Mail",
            "beschreibung": (
                f"Automatisch angelegt aus E-Mail '{email_content.subject}'.\n"
                f"Mandant: {safe_get(case_data, 'mandant', 'vorname')} {safe_get(case_data, 'mandant', 'nachname')}\n"
                f"Versicherung: {safe_get(case_data, 'gegner_versicherung', 'name')}\n"
                f"Bitte Daten prüfen und vervollständigen."
            ),
            "faellig_am": datetime.date.today().isoformat()
        }
        await django_client.create_ticket(ticket_payload)
        logger.info(f"Job {job_id}: Created review ticket")
        
        logger.info(f"Job {job_id}: Completed successfully")

    except Exception as e:
        logger.error(f"Job {job_id}: Failed with error: {str(e)}")


@app.post("/api/akte/create-from-email")
async def create_akte_from_email(
    background_tasks: BackgroundTasks,
    email_file: UploadFile = File(...),
):
    """
    Erstellt eine neue Akte aus E-Mail und Anhängen via Background Task
    """
    job_id = str(uuid.uuid4())
    
    # Read file content immediately to avoid "closed file" in background task
    content = await email_file.read()
    filename = email_file.filename
    
    # Start processing in background with bytes
    background_tasks.add_task(process_email_background_task, job_id, content, filename)
    
    return {
        "status": "accepted",
        "job_id": job_id,
        "message": "E-Mail wird verarbeitet. Akte wird im Hintergrund erstellt."
    }


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """
    Gibt den Status eines Jobs zurück
    """
    # TODO: Implement real state store
    return {
        "job_id": job_id,
        "status": "processing", # Mock status
        "message": "Check logs for details"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug
    )
