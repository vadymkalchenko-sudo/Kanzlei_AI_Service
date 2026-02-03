"""
Loki (Local LLM) Client - Single-Model Architecture
Uses Qwen 2.5:14b for one-step extraction
"""
import httpx
import json
import time
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class LokiClient:
    """Client for local Ollama/LLM (Loki) with single-model architecture"""
    
    def __init__(self):
        """Initialize Loki client"""
        self.base_url = settings.loki_url
        self.model = settings.loki_model
        logger.info(f"Loki client initialized: {self.base_url}")
        logger.info(f"  Model: {self.model}")
    
    async def extract_akte_data(self, email_content: str, attachments_info: list) -> dict:
        """
        Single-step extraction process with Qwen
        
        Args:
            email_content: E-Mail Inhalt (Text)
            attachments_info: Liste mit Anhang-Informationen
            
        Returns:
            Dictionary mit extrahierten Daten + Metriken
        """
        start_time = time.time()
        
        prompt = f"""Du bist ein Datenextraktions-Assistent für eine Rechtsanwaltskanzlei.

Analysiere die folgende E-Mail (inklusive Header, Signatur, Footer) UND die angehängten Bilder/Dokumente (z.B. Fahrzeugscheine, Unfallskizzen).

WICHTIG:
1. Suche aktiv nach Telefonnummern und E-Mail-Adressen des Mandanten.
2. Fahrzeugschein-Analyse (Scan/Foto): 
   - Extrahiere Kennzeichen, Halter, VIN.
   - Extrahiere Technische Daten: Marke (D.1) und Modell/Handelsbezeichnung (D.3). Achtung: Feld J (Fahrzeugklasse) ist NICHT das Modell!
   - Nennleistung in KW (P.2), Erstzulassung (B).
3. Suche nach Unfalldaten (Datum, Ort, Kennzeichen, Schadennummer).
4. Achte auf MEHRERE Kennzeichen (z.B. Anhänger).

E-MAIL:
{email_content[:15000]}

ANHÄNGE:
{', '.join([att.get('filename', 'unknown') for att in attachments_info])}

AUFGABE:
Extrahiere die Daten direkt im Django-Schema-Format:

{{
  "mandant": {{
    "vorname": "", "nachname": "", "anrede": "Herr/Frau",
    "adresse": {{ "strasse": "", "hausnummer": "", "plz": "", "ort": "" }},
    "email": "", "telefon": ""
  }},
  "gegner_versicherung": {{
    "name": "", "schadennummer": "",
    "adresse": {{ "strasse": "", "hausnummer": "", "plz": "", "ort": "" }}
  }},
  "unfall": {{
    "datum": "YYYY-MM-DD", "ort": "",
    "kennzeichen_gegner": "", 
    "kennzeichen_mandant": "",
    "weitere_kennzeichen": []
  }},
  "fahrzeug": {{
    "typ": "Marke Modell",
    "kw": "110",
    "ez": "YYYY-MM-DD"
  }},
  "betreff": "Verkehrsunfall vom [Datum]",
  "zusammenfassung": "Kurze Beschreibung des Unfalls",
  "handlungsbedarf": "Akte prüfen und Mandant kontaktieren"
}}

REGELN:
1. Trenne "Max Mustermann" in vorname="Max", nachname="Mustermann"
2. Trenne "Berliner Str. 1" -> strasse="Berliner Str.", hausnummer="1"
3. Wenn Daten fehlen, setze null. ERFINDE KEINE DATEN!
4. Erste Person = Mandant, Erste Versicherung = Gegner

Antworte NUR mit validem JSON, ohne Markdown, ohne Erklärungen.
"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=120.0
                )
                response.raise_for_status()
                
                result = response.json()
                response_text = result.get("response", "")
                
                # Parse JSON
                try:
                    parsed = json.loads(response_text)
                    total_time = time.time() - start_time
                    
                    return {
                        "raw_response": response_text,
                        "parsed_data": parsed,
                        "metrics": {
                            "total_extraction_time": total_time,
                            "llm_provider_used": "loki",
                            "fallback_triggered": False
                        }
                    }
                except json.JSONDecodeError as e:
                    logger.error(f"Qwen returned invalid JSON: {e}")
                    logger.error(f"Raw response: {response_text[:500]}")
                    raise
                
        except Exception as e:
            logger.error(f"Loki API error: {str(e)}")
            raise


# Global instance
loki_client = LokiClient() if settings.llm_provider == "loki" else None
