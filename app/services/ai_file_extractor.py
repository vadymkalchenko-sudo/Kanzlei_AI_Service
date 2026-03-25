import io
import logging
from email.parser import BytesParser
from fastapi import UploadFile
from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)

# Minimale Zeichenanzahl aus pypdf — darunter gilt das PDF als Scan → Vision Fallback
_PDF_TEXT_MIN_CHARS = 150


class FileExtractor:
    """Extrahiert Text aus hochgeladenen Dokumenten (.pdf, .docx, .msg, .eml, .txt, .jpg/.jpeg/.png).

    Strategie:
    - Text-basierte Formate (msg, eml, docx, txt): direkte Extraktion
    - PDF: erst pypdf, bei zu wenig Text (<150 Zeichen) Gemini Vision Fallback
    - Bilder (jpg, jpeg, png): direkt Gemini Vision (gleicher Mechanismus wie Aktenanlage)
    """

    @staticmethod
    async def extract_text(file: UploadFile) -> str:
        content = await file.read()
        return FileExtractor.extract_text_from_bytes(content, file.filename)

    @staticmethod
    def extract_text_from_bytes(content: bytes, filename: str) -> str:
        """Extrahiert Text aus Bytes — nutzbar ohne UploadFile (z.B. Batch-Indexierung)."""
        filename_lower = filename.lower()

        if filename_lower.endswith(".pdf"):
            return FileExtractor._extract_pdf(content)
        elif filename_lower.endswith(".docx"):
            return FileExtractor._extract_docx(content)
        elif filename_lower.endswith(".msg"):
            return FileExtractor._extract_msg(content)
        elif filename_lower.endswith(".eml"):
            return FileExtractor._extract_eml(content)
        elif filename_lower.endswith(".txt"):
            return content.decode("utf-8", errors="replace")
        elif filename_lower.endswith(".jpg") or filename_lower.endswith(".jpeg"):
            return FileExtractor._extract_via_gemini_vision(content, "image/jpeg")
        elif filename_lower.endswith(".png"):
            return FileExtractor._extract_via_gemini_vision(content, "image/png")
        else:
            logger.warning(f"Nicht unterstütztes Dateiformat für Text-Extraktion: {filename}")
            return ""

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        """
        Extrahiert Text aus PDFs — zweistufig:
        1. pypdf (schnell, kostenlos) — für text-basierte PDFs
        2. Gemini Vision Fallback — wenn pypdf zu wenig liefert (Scan-PDF erkannt)
           Gemini liest dann die gesamte Seite inklusive eingebetteter Bilder,
           Tabellen, Stempel und handschriftlicher Notizen.
        """
        try:
            pdf_reader = PdfReader(io.BytesIO(content))
            pages: list[str] = []
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            text = "\n".join(pages).strip()
        except Exception as e:
            logger.warning(f"pypdf Fehler: {e} — versuche Gemini Vision")
            text = ""

        if len(text) >= _PDF_TEXT_MIN_CHARS:
            return text

        # Scan-PDF oder bild-dominiertes Gutachten erkannt → Gemini Vision
        logger.info(
            f"PDF-Text zu kurz ({len(text)} Zeichen) — Scan/Bild-PDF erkannt, "
            f"starte Gemini Vision (liest auch eingebettete Bilder und Tabellen)"
        )
        vision_text = FileExtractor._extract_via_gemini_vision(content, "application/pdf")
        return vision_text if vision_text else text

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        doc = Document(io.BytesIO(content))
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()]).strip()

    @staticmethod
    def _extract_msg(content: bytes) -> str:
        """Extrahiert Text aus Outlook .msg Dateien (extract-msg Library).

        extract_msg / olefile öffnet Sub-Objekte (Attachments, Properties) intern
        erneut über den originalen File-Handle. BytesIO wird dabei nach dem ersten
        read() als 'closed' betrachtet → I/O error.
        Lösung: temporäre Datei auf Disk schreiben, damit olefile einen stabilen
        Datei-Pfad hat.
        """
        import tempfile
        import os
        tmp_path: str | None = None
        result: str = ""
        try:
            import extract_msg  # type: ignore[import-untyped]

            # Temporäre .msg-Datei anlegen — olefile öffnet Sub-Objekte intern erneut
            # über den originalen Handle. Mit BytesIO kommt es zu "I/O on closed file".
            with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            msg = extract_msg.openMsg(tmp_path)
            parts: list[str] = []
            if msg.subject:
                parts.append(f"Betreff: {msg.subject}")
            if msg.sender:
                parts.append(f"Von: {msg.sender}")
            if msg.date:
                parts.append(f"Datum: {msg.date}")
            if msg.to:
                parts.append(f"An: {msg.to}")
            body: str = msg.body or ""
            if body.strip():
                parts.append(f"\n{body.strip()}")
            msg.close()
            result = "\n".join(parts).strip()
        except Exception as e:
            logger.error(f"Fehler beim Parsen der .msg Datei: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return result

    @staticmethod
    def _extract_eml(content: bytes) -> str:
        """Extrahiert Text aus .eml Dateien (Standard-Email-Format)."""
        try:
            msg = BytesParser().parsebytes(content)
            parts: list[str] = []
            if msg.get("Subject"):
                parts.append(f"Betreff: {msg.get('Subject')}")
            if msg.get("From"):
                parts.append(f"Von: {msg.get('From')}")
            if msg.get("Date"):
                parts.append(f"Datum: {msg.get('Date')}")
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        raw = part.get_payload(decode=True)
                        if isinstance(raw, bytes):
                            parts.append(f"\n{raw.decode('utf-8', errors='replace').strip()}")
                        break
            else:
                raw = msg.get_payload(decode=True)
                if isinstance(raw, bytes):
                    parts.append(f"\n{raw.decode('utf-8', errors='replace').strip()}")
            return "\n".join(parts).strip()
        except Exception as e:
            logger.error(f"Fehler beim Parsen der .eml Datei: {e}")
            return ""

    @staticmethod
    def _extract_via_gemini_vision(content: bytes, mime_type: str) -> str:
        """
        Nutzt Gemini Vision um Text aus Bildern oder Scan-PDFs zu extrahieren.

        Nutzt denselben Client wie ai_extractor.py (Vertex AI oder Gemini API
        je nach LLM_PROVIDER) — kein hardcodierter API-Key mehr.

        Besonders wertvoll für:
        - Kfz-Gutachten (Schadensfotos mit Markierungen, Kostentabellen als Bild)
        - Eingescannte Briefe und Behördenschreiben
        - Fahrzeugscheine (Scan/Foto)
        """
        try:
            from google import genai
            from google.genai import types as genai_types
            from app.config import settings

            # Client identisch mit ai_extractor.py aufbauen
            if settings.llm_provider == "vertex":
                if not settings.vertex_project_id:
                    logger.error("VERTEX_PROJECT_ID nicht konfiguriert — Vision-Extraktion übersprungen")
                    return ""
                import os
                if settings.google_application_credentials:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
                client = genai.Client(
                    vertexai=True,
                    project=settings.vertex_project_id,
                    location=settings.vertex_location,
                )
                model_name = settings.gemini_model
                logger.info(f"[LLM: VERTEX AI] Vision-Extraktion | Modell: {model_name}")
            else:
                if not settings.gemini_api_key:
                    logger.warning("GEMINI_API_KEY nicht gesetzt — Vision-Extraktion übersprungen")
                    return ""
                client = genai.Client(api_key=settings.gemini_api_key)
                model_name = settings.gemini_model
                logger.info(f"[LLM: GEMINI API] Vision-Extraktion | Modell: {model_name}")

            prompt = (
                "Extrahiere den vollständigen Text aus diesem Dokument. "
                "Behalte alle Zahlen, Datumsangaben, Adressen, Namen, "
                "Kennzeichen, Schadensbeträge und Tabelleninhalte vollständig. "
                "Gib nur den extrahierten Text zurück, keine Erklärungen."
            )
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    prompt,
                    genai_types.Part.from_bytes(data=content, mime_type=mime_type),
                ],
            )

            text = response.text.strip() if response.text else ""
            logger.info(f"Vision-Extraktion: {len(text)} Zeichen extrahiert ({mime_type})")
            return text

        except Exception as e:
            logger.error(f"Vision-Extraktion Fehler ({mime_type}): {e}")
            return ""
