"""
FastAPI Main Application — Kanzlei AI Service
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import logging
import uuid
import asyncio

from app.config import settings
from app.services.email_processor import email_processor
from app.services.ai_extractor import ai_extractor
from app.services.django_client import django_client
from app.job_tracker import job_tracker

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Kanzlei AI Service",
    description="KI-gestützter Service für automatisierte Aktenanlage und Vorlagen-Empfehlung",
    version="0.2.0",
    debug=settings.debug
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: In Produktion einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# REQUEST/RESPONSE MODELLE
# ===========================================================================

class BausteinInfo(BaseModel):
    """Minimale Baustein-Info für Suggest-Request"""
    id: int
    kategorie: str
    titel: str
    tags: List[str] = []


class VorlagenSuggestRequest(BaseModel):
    """Request-Modell für POST /api/vorlagen/suggest"""
    vorlage_typ: str                          # versicherung_brief | mandant_info
    fragebogen_data: dict                     # Fragebogen-Felder der Akte
    verfuegbare_bausteine: List[BausteinInfo] # Bausteine aus Django-DB


class VorlagenSuggestResponse(BaseModel):
    """Response-Modell für POST /api/vorlagen/suggest"""
    vorgeschlagene_bausteine: dict
    bedingte_bloecke: List[dict]
    unfalltyp_erkannt: str
    confidence_gesamt: float
    fallback_modus: bool                      # True = Gemini nicht genutzt


# ===========================================================================
# HELPER: Gemini-Client (lazy init, None wenn kein API-Key)
# ===========================================================================

_gemini_client = None
_gemini_init_done = False

def get_gemini_client():
    global _gemini_client, _gemini_init_done
    if _gemini_init_done:
        return _gemini_client
    _gemini_init_done = True
    if settings.gemini_api_key:
        try:
            from app.services.gemini_client import GeminiClient
            _gemini_client = GeminiClient()
            logger.info(f"✓ Gemini-Client bereit: {settings.gemini_model}")
        except Exception as e:
            import traceback
            logger.error(f"✗ Gemini-Client FEHLER: {e}")
            logger.error(traceback.format_exc())
    else:
        logger.warning("Gemini API Key nicht gesetzt — Keyword-Fallback")
    return _gemini_client


# ===========================================================================
# ENDPUNKTE
# ===========================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Kanzlei AI Service",
        "version": "0.2.0",
        "status": "running",
        "provider": settings.llm_provider,
        "gemini_configured": bool(settings.gemini_api_key),
    }


@app.get("/health")
async def health_check():
    """Health check — wird vom Django-Backend alle 60s abgefragt"""
    return {
        "status": "healthy",
        "provider": settings.llm_provider,
        "backend_url": settings.backend_url,
        "gemini_available": bool(settings.gemini_api_key),
    }


@app.post("/api/vorlagen/suggest", response_model=VorlagenSuggestResponse)
async def vorlagen_suggest(request: VorlagenSuggestRequest):
    """
    KI-Baustein-Empfehlung für Erstanschreiben.
    """
    try:
        from app.services.vorlagen_suggest_service import erstelle_suggest_antwort

        logger.info(
            f"Vorlagen-Suggest: vorlage_typ={request.vorlage_typ}, "
            f"schadenshergang_len={len(request.fragebogen_data.get('schadenshergang', ''))}"
        )

        bausteine_dicts = [b.dict() for b in request.verfuegbare_bausteine]
        gemini = get_gemini_client()

        ergebnis = await erstelle_suggest_antwort(
            fragebogen_data=request.fragebogen_data,
            vorlage_typ=request.vorlage_typ,
            verfuegbare_bausteine=bausteine_dicts,
            gemini_client=gemini,
        )

        logger.info(
            f"Suggest-Ergebnis: unfalltyp={ergebnis['unfalltyp_erkannt']}, "
            f"confidence={ergebnis['confidence_gesamt']:.2f}, "
            f"fallback={ergebnis['fallback_modus']}"
        )

        return VorlagenSuggestResponse(**ergebnis)

    except Exception as e:
        logger.error(f"Fehler in vorlagen_suggest: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"KI-Analyse fehlgeschlagen: {str(e)}"
        )


class RagIngestRequest(BaseModel):
    """Daten für das Hinzufügen eines Textes in den RAG Speicher"""
    text: str
    metadata: dict  # z.B. {"fall_typ": "Auffahrunfall", "akte": "Muster-123"}
    chunk_size: int = 1000  # Zeichen pro Chunk


@app.post("/api/rag/ingest")
async def rag_ingest_document(request: RagIngestRequest):
    """
    Speichert einen Text (z.B. ein erfolgreiches Kanzleischreiben) im ChromaDB Vektor-Store.
    Der Text wird vorher in Chunks zerteilt.
    """
    try:
        from app.services.rag_store import rag_store
        
        # 1. Simples Chunking (basierend auf Zeichenanzahl und Absätzen)
        # TODO: Später kann dies auf token-basiertes Chunking umgestellt werden
        raw_text = request.text.strip()
        if not raw_text:
            raise HTTPException(status_code=400, detail="Kein Text zum Speichern übergeben.")
            
        chunks = []
        # Teile zuerst am doppelten Zeilenumbruch (Absätze)
        paragraphs = raw_text.split("\n\n")
        
        current_chunk = ""
        for p in paragraphs:
            if len(current_chunk) + len(p) < request.chunk_size:
                current_chunk += p + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
                
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        # 2. Speichere im RAG Store
        # Generiere eindeutige IDs für jeden Chunk
        base_uuid = str(uuid.uuid4())
        base_id = base_uuid[:8]
        ids = [f"doc_{base_id}_chunk_{i}" for i in range(len(chunks))]
        # Gleiche Metadaten für alle Chunks dieses Dokuments
        metadatas = [request.metadata.copy() for _ in range(len(chunks))]
        
        success = await rag_store.add_documents(
            documents=chunks,
            metadatas=metadatas,
            ids=ids
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Fehler beim Speichern in ChromaDB")
            
        logger.info(f"RAG Ingest erfolgreich: {len(chunks)} Chunks erstellt für {request.metadata.get('fall_typ', 'Unbekannt')}")
        
        return {
            "status": "success",
            "chunks_created": len(chunks),
            "document_id": base_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler in rag_ingest: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Injektion in RAG Store fehlgeschlagen: {str(e)}"
        )


class RagSearchRequest(BaseModel):
    """Daten für die RAG Suche nach Referenzschreiben"""
    query: str
    fall_typ: Optional[str] = None  # Optionaler Filter
    k_results: int = 3


@app.post("/api/rag/search")
async def rag_search_documents(request: RagSearchRequest):
    """
    Sucht in der lokalen ChromaDB nach den ähnlichsten Text-Chunks.
    Wird vom Prompt-Builder genutzt, um "Context" in den LLM-Call zu injizieren.
    """
    try:
        from app.services.rag_store import rag_store
        
        filter_dict = None
        if request.fall_typ:
            filter_dict = {"fall_typ": request.fall_typ}
            
        matches = rag_store.search_similar(
            query_text=request.query,
            n_results=request.k_results,
            filter_dict=filter_dict
        )
        
        return {
            "status": "success",
            "matches": matches
        }
    except Exception as e:
        logger.error(f"Fehler in rag_search: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Fehler bei der semantischen Suche: {str(e)}"
        )


class RagDraftRequest(BaseModel):
    """Daten für die Generierung eines Briefentwurfs via Orchestrator"""
    fall_daten: dict
    notizen: str
    fall_typ: Optional[str] = None


@app.post("/api/rag/draft")
async def rag_generate_draft(request: RagDraftRequest):
    """
    Kombiniert RAG-Wissen mit einem LLM-Aufruf, um einen echten Brief zu entwerfen.
    """
    try:
        from app.services.rag_store import rag_store
        from app.services.orchestrator import orchestrator_service
        
        # 1. Sammle Kontext (Ähnliche Fälle)
        filter_dict = {"fall_typ": request.fall_typ} if request.fall_typ else None
        
        # Erzeuge einen Suchstring aus Notizen + relevanten Falldaten
        query_parts = [request.notizen]
        if "schadenshergang" in request.fall_daten:
            query_parts.append(request.fall_daten["schadenshergang"])
            
        search_query = " ".join(query_parts)
        
        matches = rag_store.search_similar(
            query_text=search_query,
            n_results=3,
            filter_dict=filter_dict
        )
        
        # 2. Generiere den Briefentwurf (Super-Prompt)
        draft_text = await orchestrator_service.generate_draft(
            fall_daten=request.fall_daten,
            notizen=request.notizen,
            rag_context=matches
        )
        
        return {
            "status": "success",
            "draft_text": draft_text,
            "rag_matches_used": len(matches)
        }
    except Exception as e:
        logger.error(f"Fehler in rag_draft: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Fehler bei der Briefgenerierung: {str(e)}"
        )


@app.get("/api/rag/stats")
async def rag_get_stats():
    """
    Liefert Statistiken (Anzahl Dokumente, Sättigung) über die RAG-Wissensdatenbank.
    """
    try:
        from app.services.rag_store import rag_store
        stats = rag_store.get_stats()
        
        if stats.get("status") == "error":
            raise HTTPException(status_code=500, detail=stats.get("message", "Fehler beim Lesen der Stats"))
            
        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler in rag_stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Konnte RAG Statistiken nicht laden: {str(e)}"
        )


@app.delete("/api/rag/delete/{document_id}")
async def rag_delete_document(document_id: str):
    """
    Löscht ein bestimmtes Dokument (und alle seine Chunks) aus dem RAG Speicher.
    """
    try:
        from app.services.rag_store import rag_store
        
        # Validierung (Basisschutz)
        if not document_id or len(document_id) < 4:
             raise HTTPException(status_code=400, detail="Ungültige Document-ID")
             
        success = rag_store.delete_document(document_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Fehler beim Löschen im RAG Store")
            
        return {
            "status": "success",
            "deleted_document": document_id,
            "message": f"Dokument {document_id} erfolgreich aus dem KI-Wissen entfernt."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler in rag_delete: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Löschvorgang fehlgeschlagen: {str(e)}"
        )

async def process_email_background_task(job_id: str, email_content_bytes: bytes, filename: str):
    """
    Background task to process the email and create structures in Django
    """
    try:
        # Initialize job tracking
        job_tracker.create_job(job_id)
        logger.info(f"Job {job_id}: Starting processing for {filename}")
        
        # 1. Parse Email
        email_content = await email_processor.process_email(email_content_bytes, filename)
        logger.info(f"Job {job_id}: Extracted email subject '{email_content.subject}'")

        # 2. Extract Data with AI
        job_tracker.update_step(job_id, 'email_analysis', 'completed', 'E-Mail analysiert')
        job_tracker.update_step(job_id, 'mandant_creation', 'processing', 'Mandant wird erstellt...')
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
        mandant_payload = {
            "vorname": case_data.mandant.vorname or "",
            "nachname": case_data.mandant.nachname or "",
            # ansprache removed - backend uses default "Herr"
            "strasse": case_data.mandant.adresse.strasse or "",
            "hausnummer": case_data.mandant.adresse.hausnummer or "",
            "plz": case_data.mandant.adresse.plz or "",
            "stadt": case_data.mandant.adresse.ort or "",
            "email": case_data.mandant.email or "",
            "telefon": case_data.mandant.telefon or "",
            "ignore_conflicts": True 
        }
        mandant_resp = await django_client.create_mandant(mandant_payload)
        mandant_id = mandant_resp['mandant_id']
        logger.info(f"Job {job_id}: Created Mandant {mandant_id}")
        job_tracker.update_step(job_id, 'mandant_creation', 'completed', 'Mandant erstellt')
        job_tracker.update_step(job_id, 'akte_creation', 'processing', 'Akte wird erstellt...')

        # 4. Lookup/Create Gegner
        gegner_name = case_data.gegner_versicherung.name
        if not gegner_name or not gegner_name.strip():
            gegner_name = "Unbekannte Versicherung"

        # Handle missing address (Versicherung kann unbekannt sein)
        if case_data.gegner_versicherung.adresse:
            gegner_strasse = case_data.gegner_versicherung.adresse.strasse or ""
            gegner_hausnummer = case_data.gegner_versicherung.adresse.hausnummer or ""
            gegner_plz = case_data.gegner_versicherung.adresse.plz or ""
            gegner_stadt = case_data.gegner_versicherung.adresse.ort or ""
        else:
            gegner_strasse = ""
            gegner_hausnummer = ""
            gegner_plz = ""
            gegner_stadt = ""

        gegner_payload = {
            "name": gegner_name,
            "strasse": gegner_strasse,
            "hausnummer": gegner_hausnummer,
            "plz": gegner_plz,
            "stadt": gegner_stadt,
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
                "betreff": case_data.betreff,
                "unfalldatum": case_data.unfall.datum,
                "unfallort": case_data.unfall.ort,
                "kennzeichen_gegner": case_data.unfall.kennzeichen_gegner,
                "kennzeichen_mandant": case_data.unfall.kennzeichen_mandant,
                "weitere_kennzeichen": case_data.unfall.weitere_kennzeichen,
                "versicherungsnummer": case_data.gegner_versicherung.schadennummer,
                "zusammenfassung": case_data.zusammenfassung
            },
            "fragebogen_data": {
                # Mapping auf flache Frontend-Struktur (FragebogenData interface)
                "datum_zeit": case_data.unfall.datum,
                "unfallort": case_data.unfall.ort,
                "kfz_kennzeichen": case_data.unfall.kennzeichen_mandant,
                
                "vers_gegner": case_data.gegner_versicherung.name,
                "gegner_kfz": case_data.unfall.kennzeichen_gegner,
                "schaden_nr": case_data.gegner_versicherung.schadennummer,
                
                # Neue Fahrzeugdaten
                "kfz_typ": case_data.fahrzeug.typ,
                "kfz_kw_ps": case_data.fahrzeug.kw,
                "kfz_ez": case_data.fahrzeug.ez,
                
                # Defaults
                "polizei": False,
                "zeugen": False
            }
        }
        akte_resp = await django_client.create_akte(akte_payload)
        akte_id = akte_resp['akte_id']
        aktenzeichen = akte_resp.get('aktenzeichen')
        logger.info(f"Job {job_id}: Created Akte {akte_id} ({aktenzeichen})")
        job_tracker.update_step(job_id, 'akte_creation', 'completed', 'Akte erstellt')
        job_tracker.update_step(job_id, 'document_upload', 'processing', 'Dokumente werden hochgeladen...')

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
        
        job_tracker.update_step(job_id, 'document_upload', 'completed', 'Dokumente hochgeladen')
        job_tracker.update_step(job_id, 'ticket_creation', 'processing', 'Ticket wird erstellt...')

        # 8. Create Ticket
        import datetime
        ticket_payload = {
            "akte": akte_id,
            "titel": "KI: Neue Akte aus E-Mail",
            "beschreibung": (
                f"Automatisch angelegt aus E-Mail '{email_content.subject}'.\n"
                f"Mandant: {case_data.mandant.vorname} {case_data.mandant.nachname}\n"
                f"Versicherung: {case_data.gegner_versicherung.name}\n"
                f"Bitte Daten prüfen und vervollständigen."
            ),
            "faellig_am": datetime.date.today().isoformat()
        }
        await django_client.create_ticket(ticket_payload)
        logger.info(f"Job {job_id}: Created review ticket")
        job_tracker.update_step(job_id, 'ticket_creation', 'completed', 'Ticket erstellt')
        
        # Mark job as completed
        job_tracker.complete_job(job_id, akte_id, aktenzeichen)
        logger.info(f"Job {job_id}: Completed successfully")

    except Exception as e:
        logger.error(f"Job {job_id}: Failed with error: {str(e)}")
        job_tracker.fail_job(job_id, str(e))


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
    """
    Gibt den Status eines Jobs zurück
    """
    job = job_tracker.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug
    )
