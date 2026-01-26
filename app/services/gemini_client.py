"""
Google Gemini API Client
"""
import google.generativeai as genai
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini API"""
    
    def __init__(self):
        """Initialize Gemini client"""
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")
        
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)
        logger.info(f"Gemini client initialized with model: {settings.gemini_model}")
    
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
            response = self.model.generate_content(prompt)
            logger.info("Gemini extraction successful")
            
            # TODO: Parse response into structured data
            return {
                "raw_response": response.text,
                "parsed_data": {}  # TODO: Implement parsing
            }
            
        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            raise
    
    def _build_extraction_prompt(self, email_content: str, attachments_info: list) -> str:
        """Erstellt den Prompt für die Datenextraktion"""
        
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
gemini_client = GeminiClient() if settings.llm_provider == "gemini" else None
