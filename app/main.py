"""
FastAPI Main Application — Kanzlei AI Service
"""
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, BackgroundTasks, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import logging
import uuid
import asyncio

from app.config import settings
from app.services.email_processor import email_processor
from app.services.ai_extractor import ai_extractor
from app.services.ai_file_extractor import FileExtractor
from app.services.django_client import django_client
from app.services.query_service import query_service
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


class VerifyDocumentRequest(BaseModel):
    akte_id: int
    textzeilen: list[str]

class EmailSendenRequest(BaseModel):
    an: str
    betreff: str
    text: str


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

def verify_hmac(
    x_ki_signature: Optional[str] = Header(None, alias="X-KI-Signature"),
    authorization: Optional[str] = Header(None)
):
    from app.services.hmac_auth import verify_ki_signature
    auth_header = x_ki_signature or authorization
    if not verify_ki_signature(auth_header):
        raise HTTPException(status_code=403, detail="Ungültige oder fehlende HMAC-Signatur")


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


@app.post("/api/vorlagen/suggest", response_model=VorlagenSuggestResponse, dependencies=[Depends(verify_hmac)])
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
    chunk_size: int = 500  # Zeichen pro Chunk für granularere Bausteine


class IndexDokumentRequest(BaseModel):
    """Request-Modell für POST /api/rag/index_dokument/ (A3)"""
    akte_id: int
    dokument_id: int
    titel: str
    kategorie: str = ""
    text: str


@app.post("/api/rag/index_dokument/", dependencies=[Depends(verify_hmac)])
async def rag_index_dokument(request: IndexDokumentRequest):
    """
    A3: Indexiert ein Akte-Dokument in der ChromaDB Collection 'akte_dokumente'.

    Wird vom Django-Backend nach jedem Dokument-Upload als BackgroundTask aufgerufen.
    Extrahierter Text wird in ~400-Wort-Chunks mit 50-Wort-Overlap gespeichert.
    Bestehende Chunks für diese dokument_id werden zuvor gelöscht (Re-Indexierung).

    Request Body:
        { "akte_id": 42, "dokument_id": 123, "titel": "Gutachten", "kategorie": "Gutachten", "text": "..." }

    Response:
        { "status": "indexed", "chunks": 5, "dokument_id": 123 }
    """
    try:
        from app.services.rag_store import rag_store

        if not request.text or not request.text.strip():
            raise HTTPException(
                status_code=400,
                detail="Kein Text zum Indexieren übergeben."
            )

        chunk_count = await rag_store.index_dokument(
            akte_id=request.akte_id,
            dokument_id=request.dokument_id,
            titel=request.titel,
            kategorie=request.kategorie,
            text=request.text,
        )

        logger.info(
            f"RAG index_dokument: Dokument {request.dokument_id} "
            f"(Akte {request.akte_id}) → {chunk_count} Chunks"
        )

        return {
            "status": "indexed",
            "chunks": chunk_count,
            "dokument_id": request.dokument_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler bei /api/rag/index_dokument/: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Indexierung fehlgeschlagen: {str(e)}"
        )


@app.post("/api/rag/index_file/", dependencies=[Depends(verify_hmac)])
async def rag_index_file(
    file: UploadFile = File(...),
    akte_id: int = Form(...),
    dokument_id: int = Form(...),
    titel: str = Form(""),
    kategorie: str = Form(""),
):
    """
    A3b: Indexiert eine Datei direkt (ohne vorherige Textextraktion durch Django).
    Django sendet die rohe Datei — Textextraktion passiert hier im AI-Service.
    Unterstützt: .pdf, .docx, .msg, .eml, .txt, .jpg/.jpeg

    Scan-PDFs und Bilder ohne extrahierbaren Text werden übersprungen (chunks=0).
    """
    try:
        from app.services.rag_store import rag_store

        content = await file.read()
        filename = file.filename or ""
        text = FileExtractor.extract_text_from_bytes(content, filename)

        if not text or not text.strip():
            logger.info(f"index_file: Kein Text extrahierbar für {filename} (Scan/Bild?) — übersprungen.")
            return {"status": "skipped", "chunks": 0, "dokument_id": dokument_id, "reason": "no_text"}

        chunk_count = await rag_store.index_dokument(
            akte_id=akte_id,
            dokument_id=dokument_id,
            titel=titel,
            kategorie=kategorie,
            text=text,
        )

        logger.info(f"index_file: {filename} → {chunk_count} Chunks (Akte {akte_id})")
        return {"status": "indexed", "chunks": chunk_count, "dokument_id": dokument_id}

    except Exception as e:
        logger.error(f"Fehler bei /api/rag/index_file/: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Indexierung fehlgeschlagen: {str(e)}")


def _chunk_text(raw_text: str, chunk_size: int = 500) -> list[str]:
    """Zerteilt Text in Chunks (Bausteine)"""
    if not raw_text:
        return []
        
    chunks = []
    # Bei PDFs gibt es oft nur einfache Zeilenumbrüche (\n), keine \n\n
    separator = "\n\n" if "\n\n" in raw_text else "\n"
    parts = raw_text.split(separator)
    
    current_chunk = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
            
        if len(current_chunk) + len(p) + 2 < chunk_size:
            current_chunk += p + "  "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = p + "  "
            
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    # Fallback: Falls ein einzelner Block immer noch viel zu riesig ist (> chunk_size + 200)
    final_chunks = []
    for c in chunks:
        if len(c) > chunk_size + 200:
            words = c.split()
            curr = ""
            for w in words:
                if len(curr) + len(w) < chunk_size:
                    curr += w + " "
                else:
                    final_chunks.append(curr.strip())
                    curr = w + " "
            if curr:
                 final_chunks.append(curr.strip())
        else:
            final_chunks.append(c)
             
    return final_chunks


@app.post("/api/rag/ingest", dependencies=[Depends(verify_hmac)])
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
            
        chunks = _chunk_text(raw_text, request.chunk_size)
        
        # 2. Speichere im RAG Store
        base_uuid = str(uuid.uuid4())
        base_id = base_uuid[:8]
        ids = [f"doc_{base_id}_chunk_{i}" for i in range(len(chunks))]
        
        # WICHTIG: document_id muss in metadaten für die Stats in rag_store.py sein!
        metadatas = []
        for _ in chunks:
            m = request.metadata.copy()
            m["document_id"] = base_id
            metadatas.append(m)
        
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


@app.post("/api/rag/search", dependencies=[Depends(verify_hmac)])
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


class SchreibenRequest(BaseModel):
    """Request-Modell für POST /api/schreiben/ (Task N-G1)"""
    user_kontext: str
    akte_kontext: dict
    schreiben_typ: Optional[str] = None


@app.post("/api/schreiben/", dependencies=[Depends(verify_hmac)])
async def generiere_schreiben(request: SchreibenRequest):
    """
    N-G1: Generiert einen Kanzlei-Brief (Fließtext) basierend auf User-Eingaben
    und dem Akten-Kontext.
    """
    gemini = get_gemini_client()
    if not gemini:
        raise HTTPException(status_code=503, detail="Gemini API ist nicht konfiguriert.")
        
    try:
        system_instruction = (
            "Du bist ein erfahrener Rechtsanwalt. Formuliere einen professionellen "
            "Brieftext basierend auf dem vom Benutzer bereitgestellten Kontext.\n\n"
            "WICHTIG: Generiere NUR den Inhalt (Fließtext).\n"
            "KEIN Briefkopf, KEINE Anrede, KEIN 'Mit freundlichen Grüßen', KEINE Signatur.\n"
            "Beginne direkt mit dem ersten inhaltlichen Absatz.\n"
            "Halte den rechtlichen Ton professionell und präzise."
        )
        
        prompt = (
            f"AKTEN-KONTEXT:\n{request.akte_kontext}\n\n"
            f"VORGABE / USER-KONTEXT:\n{request.user_kontext}\n\n"
            f"SCHREIBEN-TYP:\n{request.schreiben_typ or 'Allgemein'}\n\n"
            "Bitte generiere jetzt den Brieftext (nur Fließtext)."
        )
        
        # Nutzen der client library async via Task falls nicht nativ async implementiert
        import asyncio
        loop = asyncio.get_event_loop()
        # Hinweis: gemini_client.generate_content ist u.U. synchron in diesem Projekt
        response_text = await loop.run_in_executor(
            None, 
            lambda: gemini.generate_content(prompt, system_instruction=system_instruction)
        )
        
        return {"brief_text": response_text.strip()}
        
    except Exception as e:
        logger.error(f"Fehler bei /api/schreiben/: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Fehler bei der Brief-Generierung: {str(e)}"
        )


class AnalyseRequest(BaseModel):
    """Request-Modell für POST /api/analyse/"""
    text: str
    akte_id: int | None = None


@app.post("/api/analyse/", dependencies=[Depends(verify_hmac)])
async def analyse_text(request: AnalyseRequest):
    """
    Juristische Akten-Analyse mit RAG-Kontext.

    Falls akte_id übergeben wird:
    1. ChromaDB akte_dokumente wird nach relevantem Dokumenten-Inhalt durchsucht
    2. Die Treffer werden als Kontext in den Prompt eingebettet
    3. Gemini analysiert mit echtem Dokumenteninhalt statt nur Metadaten
    """
    gemini = get_gemini_client()
    if not gemini:
        raise HTTPException(status_code=503, detail="Gemini API ist nicht konfiguriert.")

    # ── RAG: Dokumente der Akte aus ChromaDB holen ─────────────────────────────
    rag_kontext = ""
    if request.akte_id:
        try:
            from app.services.rag_store import rag_store
            # Semantische Suche: Schadenshergang und Regulierung als Query
            rag_results = await rag_store.search_akte_dokumente(
                query_text=request.text[:500],  # Erste 500 Zeichen als Suchanfrage
                akte_id=request.akte_id,
                n_results=8,
            )
            if rag_results:
                rag_kontext = "\n\n=== DOKUMENTEN-INHALT (aus RAG-Index) ===\n"
                rag_kontext += "Die folgenden Auszüge stammen aus den tatsächlichen Dokumenten dieser Akte:\n\n"
                for i, chunk in enumerate(rag_results, 1):
                    titel = chunk.get("titel", "Unbekannt")
                    kategorie = chunk.get("kategorie", "")
                    text = chunk.get("text", "")
                    rag_kontext += f"[Dok {i}: {titel}"
                    if kategorie:
                        rag_kontext += f" ({kategorie})"
                    rag_kontext += f"]\n{text}\n\n"
                logger.info(
                    f"RAG: {len(rag_results)} Chunks für Akte {request.akte_id} geladen"
                )
            else:
                logger.info(
                    f"RAG: Keine Chunks für Akte {request.akte_id} gefunden "
                    f"(noch nicht indexiert?)"
                )
        except Exception as rag_err:
            logger.warning(f"RAG-Abfrage fehlgeschlagen (Analyse läuft ohne): {rag_err}")

    # ── Prompt zusammenbauen ───────────────────────────────────────────────────
    full_prompt = (
        "Du bist ein juristischer Assistent der Kanzlei AWR24 (Verkehrsrecht / Unfallschadensregulierung). "
        "Erstelle eine fundierte, strukturierte Analyse mit konkreten Handlungsempfehlungen.\n\n"
        + request.text
        + rag_kontext
    )

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(
            None,
            lambda: gemini.generate(full_prompt)
        )
        return {"analyse": response_text.strip()}

    except Exception as e:
        err_str = str(e).lower()
        if "quota" in err_str or "429" in err_str or "resource_exhausted" in err_str:
            logger.warning(f"Gemini Quota erschöpft bei /api/analyse/: {e}")
            raise HTTPException(
                status_code=429,
                detail=(
                    "Gemini API Kontingent erschöpft. "
                    "Bitte warte einige Minuten und versuche die Analyse erneut."
                ),
            )
        logger.error(f"Fehler bei /api/analyse/: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Fehler bei der Analyse: {str(e)}"
        )


class DocsCreateRequest(BaseModel):
    """Request-Modell für POST /api/docs/create/"""
    titel: str
    inhalt: str
    upload_pdf: bool = False


@app.post("/api/docs/create/", dependencies=[Depends(verify_hmac)])
async def create_google_doc(request: DocsCreateRequest):
    """
    Erstellt ein Google Doc (und optional ein PDF in Drive) über die Clients.
    Returns: {"doc_url": "...", "drive_url": "..."}
    """
    from app.services.google_docs_client import google_docs_client
    from app.services.google_drive_client import google_drive_client
    
    doc_url = None
    drive_url = None
    
    try:
        # 1. Google Doc erstellen
        doc_url = google_docs_client.create_doc(request.titel, request.inhalt)
        
        # 2. Optional: PDF in Google Drive laden (vereinfachte Text-to-PDF für Mock)
        if request.upload_pdf:
            # TODO: Falls ein echter PDF-Renderer wie WeasyPrint/ReportLab eingebaut ist, hier nutzen
            # Vorerst für Drive als einfaches bytestring
            fake_pdf_bytes = request.inhalt.encode("utf-8")
            pdf_filename = f"{request.titel}.pdf"
            if not pdf_filename.endswith(".pdf"):
                pdf_filename += ".pdf"
            drive_url = google_drive_client.upload_pdf(pdf_filename, fake_pdf_bytes)
            
        return {
            "doc_url": doc_url,
            "drive_url": drive_url
        }
    except Exception as e:
        logger.error(f"Fehler bei /api/docs/create/: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Fehler bei der Google Workspace Generierung: {str(e)}"
        )


@app.get("/api/calendar/events")
async def get_calendar_events(tage: int = 14):
    """Gibt die nächsten N Tage Events zurück."""
    from app.services.google_calendar_client import google_calendar_client
    events = google_calendar_client.get_upcoming_events(tage=tage)
    return {"events": events, "count": len(events)}


@app.post("/api/email/senden")
async def email_senden(request: EmailSendenRequest):
    """
    Sendet E-Mail direkt (ohne Gemini-Tool-Call).
    Für zukünftige direkte Frontend-Integration.
    """
    from app.services.google_gmail_client import google_gmail_client
    erfolg = google_gmail_client.send_email(
        an=request.an,
        betreff=request.betreff,
        text=request.text,
    )
    return {"gesendet": erfolg}


@app.post("/api/rag/draft", dependencies=[Depends(verify_hmac)])
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
        
        matches = await rag_store.search_similar(
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


@app.get("/api/rag/indexed_ids/", dependencies=[Depends(verify_hmac)])
async def rag_get_indexed_ids(akte_id: int | None = None):
    """
    Gibt alle Dokument-IDs zurück, die bereits in der 'akte_dokumente' Collection indexiert sind.
    Wird vom Django Management-Command --nur-fehlende genutzt, um bereits vorhandene Dokumente
    beim Batch-Indexieren zu überspringen.

    Query-Parameter:
        akte_id (optional): Nur IDs dieser Akte zurückgeben. Ohne Parameter: alle Akten.
    """
    try:
        from app.services.rag_store import rag_store
        ids = rag_store.get_indexed_dokument_ids(akte_id)
        return {"akte_id": akte_id, "indexed_ids": ids, "count": len(ids)}
    except Exception as e:
        logger.error(f"Fehler bei /api/rag/indexed_ids/: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rag/health", dependencies=[Depends(verify_hmac)])
async def rag_get_health():
    """Gibt den Gesundheitszustand aller 3 ChromaDB-Collections zurück."""
    try:
        from app.services.rag_store import rag_store
        return rag_store.get_health()
    except Exception as e:
        logger.error(f"Fehler in rag_health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rag/stats", dependencies=[Depends(verify_hmac)])
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


@app.delete("/api/rag/delete/{document_id}", dependencies=[Depends(verify_hmac)])
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


@app.post("/api/rag/ingest/file", dependencies=[Depends(verify_hmac)])
async def rag_ingest_file(
    file: UploadFile = File(...),
    fall_typ: str = Form(""),
    notizen: str = Form(""),
    chunk_size: int = Form(500)
):
    """
    Nimmt eine hochgeladene Datei (PDF, DOCX, TXT) entgegen,
    extrahiert den Text und fügt ihn dem RAG Store hinzu.
    """
    try:
        from app.services.rag_store import rag_store
        from app.services.ai_file_extractor import FileExtractor
        
        # 1. Text extrahieren
        extracted_text = await FileExtractor.extract_text(file)
        
        if not extracted_text or len(extracted_text.strip()) < 10:
            raise HTTPException(status_code=400, detail="Konnte keinen relevanten Text aus der Datei extrahieren.")
            
        # 1.5 Text in Chunks schneiden
        chunks = _chunk_text(extracted_text.strip(), chunk_size)
        
        if not chunks:
            raise HTTPException(status_code=400, detail="Text konnte nicht erfolgreich in Chunks zerteilt werden.")
        
        # 2. Metadaten vorbereiten
        base_uuid = str(uuid.uuid4())
        base_id = base_uuid[:8]
        
        metadatas = []
        for _ in chunks:
            m = {
                "source": file.filename,
                "fall_typ": fall_typ,
                "notizen": notizen,
                "document_id": base_id
            }
            metadatas.append(m)
            
        ids = [f"doc_{base_id}_chunk_{i}" for i in range(len(chunks))]
        
        # 3. Zum RAG Store hinzufügen
        status = await rag_store.add_documents(
            documents=chunks,
            metadatas=metadatas,
            ids=ids
        )
        
        return {
            "status": "success",
            "message": f"Datei {file.filename} erfolgreich als {len(chunks)} Chunks zu Lokis Wissen hinzugefügt.",
            "chunk_count": len(chunks) if status else 0
        }
        
    except ValueError as ve:
         raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Fehler bei Datei RAG Ingest: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Fehler beim Verarbeiten der Datei: {str(e)}"
        )


@app.delete("/api/rag/delete/{document_id}", dependencies=[Depends(verify_hmac)])
async def rag_delete_document(document_id: str):
    """
    Löscht alle Chunks für eine bestimmte document_id aus dem RAG Store.
    """
    try:
        from app.services.rag_store import rag_store
        
        if not document_id:
            raise HTTPException(status_code=400, detail="Keine document_id angegeben.")
            
        success = rag_store.delete_document(document_id)
        
        if not success:
             raise HTTPException(status_code=500, detail="Fehler beim Löschen des Dokuments aus ChromaDB.")
             
        return {
            "status": "success",
            "message": f"Dokument {document_id} erfolgreich gelöscht."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim RAG Delete: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Fehler beim Löschen des Dokuments: {str(e)}"
        )


def _classify_attachment(filename: str) -> tuple[str | None, bool]:
    """
    Gibt (mime_type, is_image) zurück.
    is_image=True  → direkt als Gemini-Vision-Input (Bilder, Scans)
    is_image=False → Text-Extraktion via FileExtractor (PDF, DOCX, TXT)
    None           → nicht unterstützt
    """
    fn = filename.lower()
    if fn.endswith(('.jpg', '.jpeg')):
        return 'image/jpeg', True
    elif fn.endswith('.png'):
        return 'image/png', True
    elif fn.endswith('.webp'):
        return 'image/webp', True
    elif fn.endswith('.pdf'):
        return 'application/pdf', False   # Text-Extraktion zuerst; Fallback auf Vision intern
    elif fn.endswith(('.docx', '.doc', '.txt')):
        return 'text/plain', False
    return None, False


async def process_email_background_task(
    job_id: str,
    email_content_bytes: bytes,
    filename: str,
    extra_attachments: list | None = None,
):
    """
    Background task: E-Mail verarbeiten und Django-Strukturen anlegen.

    Orchestrierung (wie V2 fine-tuned):
    1. E-Mail parsen → Betreff + Body als Text
    2. Anhänge klassifizieren:
       - Bilder / Scan-PDFs → als Gemini-Vision-Input (multimodal)
       - Text-PDFs / DOCX   → FileExtractor extrahiert Text (pypdf + Vision-Fallback)
    3. Kombinierten Text + Vision-Parts an ai_extractor übergeben
    4. Django-Strukturen (Mandant, Gegner, Akte, Dokumente, Ticket) anlegen
    """
    if extra_attachments is None:
        extra_attachments = []

    try:
        # Initialize job tracking
        job_tracker.create_job(job_id)
        logger.info(f"Job {job_id}: Starte Verarbeitung für {filename}")

        # ── 1. E-Mail parsen ────────────────────────────────────────────────
        email_content = await email_processor.process_email(email_content_bytes, filename)
        logger.info(f"Job {job_id}: E-Mail geparst — Betreff: '{email_content.subject}'")

        logger.info(f"Job {job_id}: {len(email_content.attachments)} Anhänge in E-Mail gefunden: {[a.filename for a in email_content.attachments]}")
        job_tracker.update_step(job_id, 'email_analysis', 'completed', 'E-Mail analysiert')
        job_tracker.update_step(job_id, 'mandant_creation', 'processing', 'Mandant wird erstellt...')

        # ── 2. Anhänge klassifizieren: Text-Extraktion (Crawler) + Vision ──
        text_parts = [f"Betreff: {email_content.subject}\n\nE-Mail Text:\n{email_content.body}"]
        ai_attachments = []   # Bilder / Scan-PDFs → Gemini Vision

        def _process_attachment_bytes(content: bytes, fname: str, label: str):
            """Extrahiert Text oder bereitet Vision-Input vor."""
            mime, is_image = _classify_attachment(fname)
            if mime is None:
                return
            if is_image:
                # Direkt als multimodales Vision-Input
                ai_attachments.append({"mime_type": mime, "data": content})
                logger.info(f"Job {job_id}: Vision-Input: {label} ({mime})")
            else:
                # FileExtractor: Text-Crawler (pypdf + Gemini-Vision-Fallback für Scans)
                extracted = FileExtractor.extract_text_from_bytes(content, fname)
                if extracted and len(extracted.strip()) >= 50:
                    text_parts.append(f"\n=== {label} ===\n{extracted.strip()}")
                    logger.info(f"Job {job_id}: Text extrahiert: {label} ({len(extracted)} Zeichen)")
                else:
                    # Fallback: als Vision-Input (z.B. Scan-PDF ohne erkennbaren Text)
                    if mime == 'application/pdf':
                        ai_attachments.append({"mime_type": mime, "data": content})
                        logger.info(f"Job {job_id}: PDF als Vision-Input (kein Text): {label}")

        # 2a. In der E-Mail eingebettete Anhänge
        for att in email_content.attachments:
            _process_attachment_bytes(att.content, att.filename, f"Anhang: {att.filename}")

        # 2b. Separat hochgeladene Dateien (aus dem Modal — bisher immer verloren!)
        for att_data in extra_attachments:
            _process_attachment_bytes(
                att_data['content'], att_data['filename'],
                f"Separater Anhang: {att_data['filename']}"
            )

        # ── 3. KI-Extraktion: Text + Vision ────────────────────────────────
        full_text = "\n\n".join(text_parts)
        case_data = await ai_extractor.extract_case_data(full_text, attachments=ai_attachments)
        logger.info(
            f"Job {job_id}: KI-Extraktion abgeschlossen "
            f"({len(ai_attachments)} Vision-Parts, {len(text_parts)} Text-Teile)"
        )

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
        mandant_name = mandant_resp.get('name') or f"{case_data.mandant.vorname} {case_data.mandant.nachname}".strip()
        logger.info(f"Job {job_id}: Created Mandant {mandant_id} ({mandant_name})")
        job_tracker.update_step(job_id, 'mandant_creation', 'completed', mandant_name)
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

        # Auto-Fill Zahlungspositionen aus KI-extrahierten Finanzdaten
        if case_data.finanzdaten:
            fd = case_data.finanzdaten
            positionen = []
            if fd.gutachten_netto is not None:
                positionen.append({
                    "beschreibung": "Schadensgutachten (netto)",
                    "soll_betrag": fd.gutachten_netto,
                    "category": "Gutachten"
                })
            if fd.sv_gebuehren is not None:
                positionen.append({
                    "beschreibung": "Sachverständigengebühren",
                    "soll_betrag": fd.sv_gebuehren,
                    "category": "SV-Kosten"
                })
            if positionen:
                try:
                    await django_client._post_request(
                        "actions/erstelle_zahlungspositionen/",
                        {"akte_id": akte_id, "positionen": positionen}
                    )
                    logger.info(f"Job {job_id}: Auto-created {len(positionen)} Zahlungsposition(en)")
                except Exception as e:
                    logger.warning(f"Job {job_id}: Zahlungspositionen Auto-Fill fehlgeschlagen: {e}")

        job_tracker.update_step(job_id, 'akte_creation', 'completed', aktenzeichen or 'Akte erstellt')
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
        
        # 7. Upload Attachments — eingebettete Anhänge aus der E-Mail
        for att in email_content.attachments:
            await django_client.upload_dokument(
                akte_id=akte_id,
                file_content=att.content,
                filename=att.filename,
                titel=att.filename
            )
            logger.info(f"Job {job_id}: Anhang hochgeladen: {att.filename}")

        # 7b. Separat hochgeladene Dateien (aus dem Modal) ebenfalls speichern
        for att_data in extra_attachments:
            await django_client.upload_dokument(
                akte_id=akte_id,
                file_content=att_data['content'],
                filename=att_data['filename'],
                titel=att_data['filename']
            )
            logger.info(f"Job {job_id}: Separater Anhang hochgeladen: {att_data['filename']}")
        
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


@app.post("/api/akte/create-from-email", dependencies=[Depends(verify_hmac)])
async def create_akte_from_email(
    background_tasks: BackgroundTasks,
    email_file: UploadFile = File(...),
    attachments: List[UploadFile] = File([]),
):
    """
    Erstellt eine neue Akte aus E-Mail und optionalen Anhängen via Background Task.
    Anhänge werden per FileExtractor (Text-Crawler) + Gemini Vision analysiert.
    """
    job_id = str(uuid.uuid4())

    # Dateiinhalte sofort lesen — Background Task darf keine offenen Streams nutzen
    content = await email_file.read()
    filename = email_file.filename

    extra_attachment_data: List[dict] = []
    for att in attachments:
        att_bytes = await att.read()
        extra_attachment_data.append({
            'filename': att.filename or 'anhang',
            'content': att_bytes,
        })

    background_tasks.add_task(
        process_email_background_task,
        job_id, content, filename, extra_attachment_data,
    )

    return {
        "status": "accepted",
        "job_id": job_id,
        "message": "E-Mail wird verarbeitet. Akte wird im Hintergrund erstellt."
    }


@app.get("/api/akte/job_status/{job_id}", dependencies=[Depends(verify_hmac)])
async def get_job_status(job_id: str):
    """
    Gibt den aktuellen Status eines Akte-Erstellungs-Jobs zurück.
    Felder: status (processing|completed|failed), current_step, steps, akte_id, aktenzeichen, error
    """
    job = job_tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


class QueryRequest(BaseModel):
    """Request-Modell für POST /api/query/"""
    query: str
    user_id: Optional[int] = None


@app.post("/api/query/", dependencies=[Depends(verify_hmac)])
async def handle_query(request: QueryRequest):
    """
    MCP-Sekretärin: Freitext → Gemini Function Calling → Django-Daten → formatiertes Ergebnis.

    Wird vom Django Orchestrator (POST /api/orchestrator/query/) aufgerufen.

    Request Body:
        { "query": "Zeig mir alle offenen Beträge im März", "user_id": 1 }

    Response:
        {
            "status": "ok",
            "result_type": "table" | "number" | "text",
            "columns": [...],       # nur bei table
            "data": [...],          # Zeilen (table), Zahl (number) oder Text
            "total": 42,            # optional (Summe oder Anzahl)
            "query_used": "get_offene_betraege"
        }
    """
    try:
        result = await query_service.handle_query(
            query=request.query,
            user_id=request.user_id or 0,
        )
        return result
    except Exception as e:
        logger.error(f"Fehler in /api/query/: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Query-Verarbeitung fehlgeschlagen: {str(e)}"
        )


@app.post("/api/chat/", dependencies=[Depends(verify_hmac)])
async def akte_chat(request: Request):
    """
    Loki Dialog-Chat (Task CHAT-G1).
    Erwartet { "akte_id": ..., "messages": [...], "kontext": {...} }
    """
    try:
        body = await request.json()
        akte_id = body.get("akte_id")
        messages = body.get("messages", [])
        kontext = body.get("kontext", {})
        
        if not akte_id:
            raise HTTPException(status_code=400, detail="akte_id fehlt")
            
        result = await query_service.handle_akte_chat(
            akte_id=akte_id,
            messages=messages,
            kontext=kontext
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler in /api/chat/: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat fehlgeschlagen: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    import platform
    import subprocess
    import time
    
    port = settings.service_port
    
    # Automatisch blockierende Prozesse auf dem Port killen (speziell für Windows/Entwicklung)
    if platform.system() == "Windows":
        try:
            print(f"Prüfe auf verwaiste Prozesse auf Port {port}...")
            cmd = f'powershell -Command "$pid_to_kill = (Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess; if ($pid_to_kill) {{ Stop-Process -Id $pid_to_kill -Force; Write-Host \'Port {port} freigegeben.\' }}"'
            subprocess.run(cmd, shell=True, capture_output=True)
            time.sleep(1)
        except Exception as e:
            print(f"Fehler beim Freigeben von Port {port}: {e}")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.debug
    )
