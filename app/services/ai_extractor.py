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
# Pydantic Models for Extraction
class ExtractedAddress(BaseModel):
    strasse: Optional[str] = None
    hausnummer: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None

# ... (Previous models remain same, skipping to keep context concise if allowed by tool, ensuring replacement covers target correctly)

# Since I need to replace ExtractedAddress AND the Prompt later in the file, I might need two chunks or one big chunk if they are close. 
# They are far apart (Lines 16 vs 150). usage of multi_replace is better.
# switching to multi_replace in next thought or just doing address first then prompt.
# I will use replace_file_content for the Model first.

class ExtractedPerson(BaseModel):
    vorname: Optional[str] = None
    nachname: Optional[str] = None
    # anrede removed - backend defaults to "Herr"
    adresse: ExtractedAddress = ExtractedAddress()
    email: Optional[str] = None
    telefon: Optional[str] = None

class ExtractedInsurance(BaseModel):
    name: Optional[str] = None
    schadennummer: Optional[str] = None
    adresse: ExtractedAddress = ExtractedAddress()

class ExtractedVehicle(BaseModel):
    typ: Optional[str] = None # z.B. VW Golf
    kw: Optional[str] = None # Nennleistung in KW
    ez: Optional[str] = None # Erstzulassung YYYY-MM-DD

class ExtractedAccident(BaseModel):
    datum: Optional[str] = None  # YYYY-MM-DD
    ort: Optional[str] = None
    kennzeichen_gegner: Optional[str] = None
    kennzeichen_mandant: Optional[str] = None
    weitere_kennzeichen: list[str] = [] # Für Anhänger oder Zweitwagen

class ExtractedFinanzdaten(BaseModel):
    gutachten_netto: Optional[float] = None  # Nettokosten Schadensgutachten
    sv_gebuehren: Optional[float] = None     # Sachverständigengebühren gesamt

class CaseData(BaseModel):
    mandant: ExtractedPerson = ExtractedPerson()
    gegner_versicherung: ExtractedInsurance = ExtractedInsurance()
    unfall: ExtractedAccident = ExtractedAccident()
    fahrzeug: ExtractedVehicle = ExtractedVehicle() # NEU: Fahrzeugdaten
    finanzdaten: Optional[ExtractedFinanzdaten] = None  # Beträge aus Rechnungen/Gutachten
    betreff: str = ""
    zusammenfassung: Optional[str] = ""
    # handlungsbedarf removed


def _clean_zero_strings(obj):
    """Bereinigt '0'-Strings → '' (Gemini liefert manchmal '0' statt '' für leere Textfelder).
    Verhindert falsche Kollisionsprüfungs-Treffer (z.B. Kennzeichen '0').
    Numerische 0-Werte (int/float) bleiben unverändert."""
    if isinstance(obj, dict):
        return {k: _clean_zero_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_zero_strings(v) for v in obj]
    if obj == "0":
        return ""
    return obj


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
        
        Two-Model Logic (Loki):
        1. Vision model extracts raw data
        2. Mapping model structures for Django
        
        Fallback: If Loki fails, permanently switch to Gemini
        """
        import httpx
        import time
        
        start_time = time.time()
        provider_used = settings.llm_provider
        fallback_triggered = False
        
        # Try Loki first (if configured)
        if settings.llm_provider == "loki":
            try:
                from app.services.loki_client import loki_client
                
                if not loki_client:
                    raise ValueError("Loki client not initialized")
                
                logger.info("🤖 Using Loki (Hybrid: Vision + Qwen Mapping)")
                
                # Call Loki two-step extraction
                result = await loki_client.extract_akte_data(text, [])
                
                # Log metrics
                metrics = result.get("metrics", {})
                logger.info(f"📊 Vision Model: {metrics.get('vision_model_time', 0):.2f}s")
                logger.info(f"📊 Qwen Mapping: {metrics.get('mapping_model_time', 0):.2f}s")
                logger.info(f"📊 Total Time: {metrics.get('total_extraction_time', 0):.2f}s")
                
                # Parse to CaseData
                parsed_data = result.get("parsed_data", {})
                case_data = CaseData(**parsed_data)
                
                # Log success
                fields_count = sum(1 for field in parsed_data.values() if field)
                logger.info(f"✅ Loki extraction successful ({fields_count} fields extracted)")
                
                return case_data
                
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
                logger.warning(f"⚠️  GPU-Server nicht erreichbar: {str(e)}")
                logger.warning("🔄 FALLBACK: Wechsel zu Gemini (permanent)")
                
                # Permanent fallback
                settings.llm_provider = "gemini"
                provider_used = "gemini"
                fallback_triggered = True
                
            except Exception as e:
                logger.error(f"❌ Loki extraction failed: {str(e)}")
                logger.warning("🔄 FALLBACK: Wechsel zu Gemini (permanent)")
                
                # Permanent fallback
                settings.llm_provider = "gemini"
                provider_used = "gemini"
                fallback_triggered = True
        
        # Use Gemini (either configured or fallback)
        if settings.llm_provider == "gemini":
            if not self.model:
                logger.info("Model not ready, trying to configure again...")
                self.configure_genai()

            if not self.model:
                logger.warning("No AI model configured, returning empty structure")
                return CaseData()
            
            if fallback_triggered:
                logger.info("🌐 Using Gemini (Fallback from Loki)")
            else:
                logger.info("🌐 Using Gemini (Configured)")

            prompt_text = f"""
            Du bist ein juristischer Assistent. Analysiere die folgende E-Mail (inklusive Header, Signatur, Footer) UND die angehängten Bilder/Dokumente.
            Extrahiere strukturierte Daten für eine neue Verkehrsrecht-Akte.
            
            WICHTIG: 
            1. Suche aktiv nach Telefonnummern und E-Mail-Adressen des Mandanten.
            2. Fahrzeuschein-Analyse (Scan/Foto): 
               - Extrahiere Kennzeichen, Halter.
               - Extrahiere Technische Daten: Marke (D.1) und Modell/Handelsbezeichnung (D.3). Achtung: Feld J (Fahrzeugklasse) ist NICHT das Modell! Nennleistung in KW (P.2), Erstzulassung (B).
            3. Suche nach Unfalldaten (Datum, Ort, Kennzeichen, Schadennummer).
            4. Achte auf MEHRERE Kennzeichen (z.B. Anhänger).
            5. **KRITISCH - Adressen-Trennung:**
               - "strasse" enthält NUR den Straßennamen (z.B. "Heideweg", "Musterstraße")
               - "hausnummer" enthält NUR die Hausnummer mit Zusätzen (z.B. "2 A", "15", "23b")
               - Beispiel: "Heideweg 2 A" → strasse: "Heideweg", hausnummer: "2 A"
               - Beispiel: "Musterstraße 15" → strasse: "Musterstraße", hausnummer: "15"
               - NIEMALS die Hausnummer in "strasse" eintragen!
            
            E-Mail Text:
            {text[:15000]}
            
            Antworte NUR mit validem JSON (ohne Markdown), das genau diesem Schema entspricht:
            {{
                "mandant": {{
                    "vorname": "Vorname", "nachname": "Nachname",
                    "adresse": {{ "strasse": "Nur Straßenname", "hausnummer": "Nur Nummer+Zusatz", "plz": "PLZ", "ort": "Ort" }},
                    "email": "Email", "telefon": "Tel"
                }},
                "gegner_versicherung": {{
                    "name": "Name Vers.", "schadennummer": "Schadennummer",
                     "adresse": {{ "strasse": "Nur Straßenname", "hausnummer": "Nur Nummer+Zusatz", "plz": "", "ort": "" }}
                }},
                "unfall": {{
                    "datum": "YYYY-MM-DD", "ort": "Ort",
                    "kennzeichen_gegner": "XX-XX-1234", 
                    "kennzeichen_mandant": "XX-YY-5678",
                    "weitere_kennzeichen": []
                }},
                "fahrzeug": {{
                    "typ": "Marke Modell (z.B. VW Touran, aus Feld D.3)",
                    "kw": "110 (nur Zahl)",
                    "ez": "YYYY-MM-DD"
                }},
                "finanzdaten": {{
                    "gutachten_netto": 1234.56,
                    "sv_gebuehren": 345.00
                }},
                "betreff": "Betreff",
                "zusammenfassung": "Zusammenfassung"
            }}

            REGELN:
            - Wenn Daten fehlen, lass das Feld leer (""). Sende KEINE null-Werte für Textfelder!
            - ERFINDE NICHTS (Keine "Unbekannt" Platzhalter)!
            - Trenne Straße und Hausnummer IMMER in separate Felder!
            - finanzdaten: Suche nach Rechnungsbeträgen/Gutachten-Kosten. Setze null wenn nicht vorhanden, keine Schätzungen!
            """

            # Prepare multimodal content parts
            content_parts = [prompt_text]
            
            if attachments:
                for att in attachments:
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

                # Bereinigung: Gemini liefert manchmal "0" statt "" für leere Textfelder.
                # Das führt zu Kollisionsprüfungs-Fehlern (Kennzeichen "0" wird als real erkannt).
                data = _clean_zero_strings(data)

                # Log metrics
                total_time = time.time() - start_time
                fields_count = sum(1 for field in data.values() if field)
                
                logger.info(f"📊 Total Time: {total_time:.2f}s")
                logger.info(f"📊 Provider: {provider_used}")
                logger.info(f"📊 Fallback Triggered: {fallback_triggered}")
                logger.info(f"✅ Gemini extraction successful ({fields_count} fields extracted)")
                
                return CaseData(**data)
                
            except Exception as e:
                logger.error(f"AI Extraction Error: {str(e)}")
                # Return empty on error to allow manual entry later
                return CaseData(zusammenfassung=f"Fehler bei KI-Analyse: {str(e)}")

ai_extractor = AIExtractor()
