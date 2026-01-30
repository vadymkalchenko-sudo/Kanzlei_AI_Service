"""
AI Extraction Service
Uses Gemini/Loki to extract structured data from text
"""
import json
import logging
from typing import Optional, Dict, Any
import google.generativeai as genai
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

# Pydantic Models for Extraction
class ExtractedAddress(BaseModel):
    strasse: str = ""
    plz: str = ""
    ort: str = ""

class ExtractedPerson(BaseModel):
    vorname: str = ""
    nachname: str = ""
    anrede: str = ""
    adresse: ExtractedAddress = ExtractedAddress()
    email: str = ""
    telefon: str = ""

class ExtractedInsurance(BaseModel):
    name: str = ""
    schadennummer: str = ""
    adresse: ExtractedAddress = ExtractedAddress()

class ExtractedAccident(BaseModel):
    datum: str = ""  # YYYY-MM-DD
    ort: str = ""
    kennzeichen_gegner: str = ""
    kennzeichen_mandant: str = ""

class CaseData(BaseModel):
    mandant: ExtractedPerson = ExtractedPerson()
    gegner_versicherung: ExtractedInsurance = ExtractedInsurance()
    unfall: ExtractedAccident = ExtractedAccident()
    betreff: str = ""
    zusammenfassung: str = ""
    handlungsbedarf: str = ""

class AIExtractor:
    def __init__(self):
        self.configure_genai()
        self.model = None

    def configure_genai(self):
        if settings.gemini_api_key:
            try:
                logger.info(f"Configuring Gemini with key length: {len(settings.gemini_api_key)}")
                genai.configure(api_key=settings.gemini_api_key)
                self.model = genai.GenerativeModel(settings.gemini_model)
                logger.info(f"Gemini Model '{settings.gemini_model}' configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure Gemini: {str(e)}")
        else:
            logger.warning("Gemini API Key not set in settings!")

    async def extract_case_data(self, text: str) -> CaseData:
        """Extracts structured case data from text using LLM"""
        # Lazy config check
        if not self.model:
            logger.info("Model not ready, trying to configure again...")
            self.configure_genai()

        if not self.model:
            # Fallback for testing/dev without key
            logger.warning("No AI model configured (still None after retry), returning empty structure")
            return CaseData()

        prompt = f"""
        Du bist ein juristischer Assistent. Analysiere die folgende E-Mail/Dokument und extrahiere strukturierte Daten für eine neue Verkehrsrecht-Akte.
        
        Bitte extrahiere folgende Informationen:
        1. Mandant (Name, Adresse, Kontakt)
        2. Gegnerische Versicherung (Name, Schadennummer)
        3. Unfall (Datum, Ort, Kennzeichen)
        4. Betreff/Zusammenfassung

        Text:
        {text[:10000]}  # Limit token usage
        
        Antworte NUR mit validem JSON, das genau diesem Schema entspricht:
        {{
            "mandant": {{
                "vorname": "", "nachname": "", "anrede": "Herr/Frau",
                "adresse": {{ "strasse": "", "plz": "", "ort": "" }},
                "email": "", "telefon": ""
            }},
            "gegner_versicherung": {{
                "name": "", "schadennummer": "",
                 "adresse": {{ "strasse": "", "plz": "", "ort": "" }}
            }},
            "unfall": {{
                "datum": "YYYY-MM-DD", "ort": "",
                "kennzeichen_gegner": "", "kennzeichen_mandant": ""
            }},
            "betreff": "Kurzer Betreff für Akte",
            "zusammenfassung": "Kurze Zusammenfassung des Inhalts",
            "handlungsbedarf": "Was muss getan werden?"
        }}
        """

        try:
            response = self.model.generate_content(prompt)
            json_str = response.text.strip()
            
            # Clean up potential markdown formatting ```json ... ```
            if json_str.startswith("```"):
                json_str = json_str.strip("`")
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            
            data = json.loads(json_str)
            return CaseData(**data)
            
        except Exception as e:
            logger.error(f"AI Extraction Error: {str(e)}")
            # Return empty on error to allow manual entry later
            return CaseData(zusammenfassung=f"Fehler bei KI-Analyse: {str(e)}")

ai_extractor = AIExtractor()
