"""
Google Gemini API Client — neues google.genai SDK (v1.x)
"""
from google import genai
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini API (neues google.genai SDK)"""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model  # z.B. "gemini-2.5-flash"
        logger.info(f"Gemini-Client initialisiert mit Modell: {self.model_name}")

    def generate(self, prompt: str) -> str:
        """Synchroner Aufruf — für run_in_executor in AsyncIO nutzbar."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text
