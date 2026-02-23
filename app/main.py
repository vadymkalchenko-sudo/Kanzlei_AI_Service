"""
FastAPI Main Application — Kanzlei AI Service
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import logging

from app.config import settings

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
    
    - Analysiert fragebogen_data.schadenshergang via Gemini
    - Erkennt Unfalltyp (Auffahrunfall, Parkschaden, etc.)
    - Empfiehlt passende Bausteine aus der übergebenen Liste
    - Bedingte Blöcke werden deterministisch berechnet (kein LLM)
    
    POST /api/vorlagen/suggest
    Body: VorlagenSuggestRequest
    """
    try:
        from app.services.vorlagen_suggest_service import erstelle_suggest_antwort

        logger.info(
            f"Vorlagen-Suggest: vorlage_typ={request.vorlage_typ}, "
            f"schadenshergang_len={len(request.fragebogen_data.get('schadenshergang', ''))}"
        )

        # Bausteine als einfache Dicts
        bausteine_dicts = [b.dict() for b in request.verfuegbare_bausteine]

        # Gemini-Client (None wenn kein Key konfiguriert → Keyword-Fallback)
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


@app.post("/api/akte/create-from-email")
async def create_akte_from_email(
    email_file: UploadFile = File(...),
    attachments: List[UploadFile] = File(default=[])
):
    """
    Erstellt eine neue Akte aus E-Mail und Anhängen.
    TODO: Vollständige Implementierung
    """
    try:
        logger.info(f"E-Mail empfangen: {email_file.filename}, Anhänge: {len(attachments)}")
        return {
            "status": "processing",
            "job_id": "placeholder-123",
            "message": "E-Mail-Verarbeitung noch nicht vollständig implementiert"
        }
    except Exception as e:
        logger.error(f"Fehler bei E-Mail-Verarbeitung: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Job-Status abfragen (TODO: echtes Job-Tracking)"""
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Job-Tracking noch nicht implementiert"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug
    )
