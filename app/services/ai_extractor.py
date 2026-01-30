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

    async def extract_case_data(self, text: str, attachments: list = None) -> CaseData:
        """
        Extracts structured case data from text and attachments using LLM.
        attachments: List of dicts {'mime_type': str, 'data': bytes}
        """
        # Lazy config check
        if not self.model:
            logger.info("Model not ready, trying to configure again...")
            self.configure_genai()

        if not self.model:
            logger.warning("No AI model configured (still None after retry), returning empty structure")
            return CaseData()

        prompt_text = f"""
        Du bist ein juristischer Assistent. Analysiere die folgende E-Mail (inklusive Header, Signatur, Footer) UND die angehängten Bilder/Dokumente (z.B. Fahrzeugscheine, Unfallskizzen).
        Extrahiere strukturierte Daten für eine neue Verkehrsrecht-Akte.
        
        WICHTIG: 
        1. Suche aktiv nach Telefonnummern und E-Mail-Adressen des Mandanten (auch in Signaturen).
        2. Fahrzeuschein-Analyse: Wenn ein Fahrzeugschein als Bild dabei ist, extrahiere Kennzeichen, Fahrzeughalter (Name/Adresse) und VIN.
        3. Suche nach Unfalldaten (Datum, Ort, Kennzeichen) im gesamten Input.
        
        E-Mail Text:
        {text[:15000]}
        
        Antworte NUR mit validem JSON (ohne Markdown), das genau diesem Schema entspricht:
        {{
            "mandant": {{
                "vorname": "Vorname (falls nicht gefunden, leer lassen)", 
                "nachname": "Nachname", 
                "anrede": "Herr/Frau",
                "adresse": {{ "strasse": "", "plz": "", "ort": "" }},
                "email": "Email des Absenders/Mandanten", 
                "telefon": "Telefonnummer aus Signatur/Text"
            }},
            "gegner_versicherung": {{
                "name": "Name der Versicherung", 
                "schadennummer": "Schadennummer/Aktenzeichen d. Versicherung",
                 "adresse": {{ "strasse": "", "plz": "", "ort": "" }}
            }},
            "unfall": {{
                "datum": "YYYY-MM-DD", 
                "ort": "Unfallort",
                "kennzeichen_gegner": "XX-XX-1234", 
                "kennzeichen_mandant": "XX-YY-5678 (ggf. aus Fahrzeugschein)"
            }},
            "betreff": "Kurzer Betreff für Akte (z.B. Unfall vom ...)",
            "zusammenfassung": "Kurze inhaltliche Zusammenfassung",
            "handlungsbedarf": "Was muss getan werden? (z.B. Anspruchsschreiben erstellen)"
        }}
        """

        # Prepare multimodal content parts
        content_parts = [prompt_text]
        
        if attachments:
            for att in attachments:
                # Gemini expects dict with 'mime_type' and 'data' keys for blob
                # We assume att is already {'mime_type': ..., 'data': ...}
                content_parts.append({
                    "mime_type": att['mime_type'],
                    "data": att['data']
                })
                logger.info(f"Added attachment to AI context: {att.get('mime_type')}")

        try:
            response = self.model.generate_content(content_parts)
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
