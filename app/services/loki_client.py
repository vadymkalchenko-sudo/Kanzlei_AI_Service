"""
Loki (Local LLM) Client - Placeholder for production
"""
import httpx
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class LokiClient:
    """Client for local Ollama/LLM (Loki)"""
    
    def __init__(self):
        """Initialize Loki client"""
        self.base_url = settings.loki_url
        self.model = settings.loki_model
        logger.info(f"Loki client initialized: {self.base_url} / {self.model}")
    
    async def extract_akte_data(self, email_content: str, attachments_info: list) -> dict:
        """
        Extrahiert Aktendaten aus E-Mail und Anhängen
        
        Args:
            email_content: E-Mail Inhalt (Text)
            attachments_info: Liste mit Anhang-Informationen
            
        Returns:
            Dictionary mit extrahierten Daten
        """
        prompt = self._build_extraction_prompt(email_content, attachments_info)
        
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
                logger.info("Loki extraction successful")
                
                return {
                    "raw_response": result.get("response", ""),
                    "parsed_data": {}  # TODO: Implement parsing
                }
                
        except Exception as e:
            logger.error(f"Loki API error: {str(e)}")
            raise
    
    def _build_extraction_prompt(self, email_content: str, attachments_info: list) -> str:
        """Erstellt den Prompt für die Datenextraktion"""
        # Same prompt as Gemini client
        prompt = f"""
Du bist ein KI-Assistent für eine Rechtsanwaltskanzlei.

Analysiere die folgende E-Mail und extrahiere alle relevanten Informationen für die Anlage einer neuen Akte.

E-MAIL:
{email_content}

ANHÄNGE:
{', '.join([att.get('filename', 'unknown') for att in attachments_info])}

AUFGABE:
Extrahiere folgende Informationen im JSON-Format:

{{
  "mandant": {{
    "name": "Vor- und Nachname",
    "strasse": "Straße und Hausnummer",
    "plz": "PLZ",
    "ort": "Ort",
    "telefon": "Telefonnummer",
    "email": "E-Mail Adresse"
  }},
  "unfall": {{
    "datum": "Unfalldatum (YYYY-MM-DD)",
    "ort": "Unfallort",
    "beschreibung": "Kurze Unfallbeschreibung"
  }},
  "gegner": {{
    "name": "Name des Unfallgegners",
    "versicherung": "Versicherung des Gegners",
    "kennzeichen": "Kennzeichen"
  }},
  "dokumente": [
    {{
      "filename": "Dateiname",
      "typ": "Dokumententyp (z.B. Unfallbericht, Gutachten, etc.)"
    }}
  ]
}}

Wenn Informationen nicht vorhanden sind, setze den Wert auf null.
Antworte NUR mit dem JSON, ohne zusätzlichen Text.
"""
        return prompt


# Global instance
loki_client = LokiClient() if settings.llm_provider == "loki" else None
