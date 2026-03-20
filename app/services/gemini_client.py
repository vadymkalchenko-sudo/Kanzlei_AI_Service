"""
Google Gemini API Client (google-genai SDK >= 1.0)
"""
from google import genai
from google.genai import types as genai_types
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client für Google Gemini API (neues google-genai SDK)"""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY nicht konfiguriert")

        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model
        logger.info(f"Gemini-Client initialisiert mit Modell: {self.model_name}")

    def generate(self, prompt: str) -> str:
        """Einfacher Text-Aufruf (synchron — für run_in_executor geeignet)."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text

    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        """Text-Aufruf mit optionaler System-Instruction."""
        if system_instruction:
            config = genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
        else:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
        return response.text
