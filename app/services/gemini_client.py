"""
Google Gemini API Client (google-generativeai SDK v0.3+)
"""
import google.generativeai as genai
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini API (neues google.genai SDK)"""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        genai.configure(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model  # z.B. "gemini-2.0-flash"
        self.model = genai.GenerativeModel(self.model_name)
        logger.info(f"Gemini-Client initialisiert mit Modell: {self.model_name}")

    def generate(self, prompt: str) -> str:
        """Synchroner Aufruf — für run_in_executor in AsyncIO nutzbar."""
        response = self.model.generate_content(prompt)
        return response.text
