"""
Loki (Local LLM) Client - Hybrid Two-Model Architecture
Vision Model: llama-vision-work (reads images)
Mapping Model: qwen-work (structures data with superior reasoning)
"""
import httpx
import json
import time
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class LokiClient:
    """Client for local Ollama/LLM (Loki) with hybrid two-model architecture"""
    
    def __init__(self):
        """Initialize Loki client"""
        self.base_url = settings.loki_url
        self.vision_model = settings.loki_vision_model
        self.mapping_model = settings.loki_mapping_model
        logger.info(f"Loki client initialized: {self.base_url}")
        logger.info(f"  Vision Model: {self.vision_model}")
        logger.info(f"  Mapping Model: {self.mapping_model}")
    
    async def extract_akte_data(self, email_content: str, attachments_info: list) -> dict:
        """
        Two-step extraction process:
        1. Vision model extracts raw data from images + text
        2. Mapping model structures data for Django
        
        Args:
            email_content: E-Mail Inhalt (Text)
            attachments_info: Liste mit Anhang-Informationen
            
        Returns:
            Dictionary mit extrahierten Daten + Metriken
        """
        start_time = time.time()
        
        try:
            # Step 1: Vision Model - Extract raw data
            logger.info("Step 1: Vision model extracting raw data...")
            vision_start = time.time()
            raw_data = await self._extract_raw_data(email_content, attachments_info)
            vision_time = time.time() - vision_start
            logger.info(f"Vision model completed in {vision_time:.2f}s")
            
            # Step 2: Mapping Model - Structure data
            logger.info("Step 2: Mapping model (Qwen) structuring data...")
            mapping_start = time.time()
            structured_data = await self._map_to_schema(raw_data)
            mapping_time = time.time() - mapping_start
            logger.info(f"Mapping model completed in {mapping_time:.2f}s")
            
            total_time = time.time() - start_time
            
            return {
                "raw_response": json.dumps(structured_data, ensure_ascii=False),
                "parsed_data": structured_data,
                "metrics": {
                    "vision_model_time": vision_time,
                    "mapping_model_time": mapping_time,
                    "total_extraction_time": total_time,
                    "llm_provider_used": "loki",
                    "fallback_triggered": False
                }
            }
            
        except Exception as e:
            logger.error(f"Loki extraction failed: {str(e)}")
            raise
    
    async def _extract_raw_data(self, email_content: str, attachments_info: list) -> dict:
        """
        Step 1: Vision model extracts raw data from email + attachments
        """
        prompt = f"""Du bist ein Datenextraktions-Assistent für eine Rechtsanwaltskanzlei.

Analysiere die folgende E-Mail (inklusive Header, Signatur, Footer) UND die angehängten Bilder/Dokumente (z.B. Fahrzeugscheine, Unfallskizzen).

WICHTIG: 
1. Suche aktiv nach Telefonnummern und E-Mail-Adressen des Mandanten.
2. Fahrzeuschein-Analyse (Scan/Foto): 
   - Extrahiere Kennzeichen, Halter, VIN.
   - Extrahiere Technische Daten: Marke (D.1) und Modell/Handelsbezeichnung (D.3). Achtung: Feld J (Fahrzeugklasse) ist NICHT das Modell! Nennleistung in KW (P.2), Erstzulassung (B).
3. Suche nach Unfalldaten (Datum, Ort, Kennzeichen, Schadennummer).
4. Achte auf MEHRERE Kennzeichen (z.B. Anhänger).

E-MAIL:
{email_content[:15000]}

ANHÄNGE:
{', '.join([att.get('filename', 'unknown') for att in attachments_info])}

AUFGABE:
Extrahiere ALLE Daten die du findest als JSON:

{{
  "personen": [
    {{"name": "Vor- und Nachname", "adresse": "Vollständige Adresse", "telefon": "Tel", "email": "Email", "anrede": "Herr/Frau"}}
  ],
  "fahrzeuge": [
    {{"kennzeichen": "XX-XX-1234", "marke_typ": "VW Golf", "kw": "110", "erstzulassung": "YYYY-MM-DD", "halter": "Name"}}
  ],
  "unfall": {{
    "datum": "YYYY-MM-DD",
    "ort": "Unfallort",
    "beschreibung": "Kurze Beschreibung",
    "kennzeichen_beteiligt": ["XX-XX-1234", "YY-YY-5678"]
  }},
  "versicherungen": [
    {{"name": "Versicherungsname", "schadennummer": "12345", "adresse": "Adresse"}}
  ]
}}

Wenn Informationen nicht vorhanden sind, setze den Wert auf null.
Antworte NUR mit validem JSON, ohne Markdown, ohne Erklärungen.
"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.vision_model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=120.0
                )
                response.raise_for_status()
                
                result = response.json()
                raw_json = result.get("response", "")
                
                # Parse JSON
                try:
                    parsed = json.loads(raw_json)
                    return parsed
                except json.JSONDecodeError as e:
                    logger.error(f"Vision model returned invalid JSON: {e}")
                    logger.error(f"Raw response: {raw_json[:500]}")
                    # Return minimal structure
                    return {"personen": [], "fahrzeuge": [], "unfall": {}, "versicherungen": []}
                
        except Exception as e:
            logger.error(f"Vision model API error: {str(e)}")
            raise
    
    async def _map_to_schema(self, raw_data: dict) -> dict:
        """
        Step 2: Qwen mapping model maps raw data to Django schema
        """
        prompt = f"""Du bist ein Daten-Mapping-Assistent für eine Rechtsanwaltskanzlei.

Nimm die folgenden extrahierten Rohdaten und mappe sie auf das Django-Schema.

ROHDATEN:
{json.dumps(raw_data, ensure_ascii=False, indent=2)}

DJANGO-SCHEMA:
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
  "betreff": "",
  "zusammenfassung": "",
  "handlungsbedarf": ""
}}

MAPPING-REGELN:
1. Trenne Namen: "Max Mustermann" -> vorname="Max", nachname="Mustermann"
2. Trenne Adressen: "Berliner Str. 1, 10115 Berlin" -> strasse="Berliner Str.", hausnummer="1", plz="10115", ort="Berlin"
3. Leite Anrede ab: "Jennifer" -> "Frau", "Thomas" -> "Herr"
4. Erste Person in "personen" = Mandant
5. Erste Versicherung = Gegner-Versicherung
6. Erstes Fahrzeug = Mandant-Fahrzeug
7. Wenn Daten fehlen, setze null. ERFINDE KEINE DATEN!
8. Betreff = "Verkehrsunfall vom [Datum]"
9. Zusammenfassung = Kurze Beschreibung des Unfalls
10. Handlungsbedarf = "Akte prüfen und Mandant kontaktieren"

Antworte NUR mit dem gemappten JSON, ohne Markdown, ohne Erklärungen.
"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.mapping_model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=120.0
                )
                response.raise_for_status()
                
                result = response.json()
                mapped_json = result.get("response", "")
                
                # Parse JSON
                try:
                    parsed = json.loads(mapped_json)
                    return parsed
                except json.JSONDecodeError as e:
                    logger.error(f"Qwen mapping model returned invalid JSON: {e}")
                    logger.error(f"Raw response: {mapped_json[:500]}")
                    # Return empty structure
                    return {}
                
        except Exception as e:
            logger.error(f"Qwen mapping model API error: {str(e)}")
            raise


# Global instance
loki_client = LokiClient() if settings.llm_provider == "loki" else None
