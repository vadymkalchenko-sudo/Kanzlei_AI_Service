from typing import Dict, Any, List
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class OrchestratorService:
    """
    Baut Super-Prompts basierend auf RAG-Kontext zusammen und kommuniziert mit Gemini.
    """
    
    def __init__(self):
        self.system_prompt = (
            "Du bist ein hochqualifizierter KI-Assistent für eine Anwaltskanzlei (Verkehrsrecht). "
            "Deine Aufgabe ist es, professionelle Erstanschreiben zu entwerfen. "
            "Nutze zwingend den juristischen Tonfall, zitiere relevante Gesetze (§ 7 StVG, § 115 VVG) "
            "und formuliere präzise Aufforderungen wie in den Beispielen, die dir als Kontext mitgegeben werden."
        )

    async def generate_draft(self, fall_daten: Dict[str, Any], notizen: str, rag_context: List[Dict[str, Any]]) -> str:
        """
        Baut den Prompt und macht einen direkten Vertex API Call (ohne Langchain/SDK).
        """
        if not settings.gemini_api_key:
            logger.error("Kein Gemini API Key für Draft Generierung vorhanden!")
            return "KI Service ist nicht konfiguriert (API Key fehlt)."
            
        # 1. Bereite RAG Kontext vor
        context_texts = []
        for i, match in enumerate(rag_context, 1):
            text = match.get("text", "")
            fall_typ = match.get("metadata", {}).get("fall_typ", "Unbekannt")
            context_texts.append(f"--- BEISPIEL {i} (Typ: {fall_typ}) ---\n{text}\n")
            
        rag_string = "\n".join(context_texts) if context_texts else "Keine spezifischen Kanzlei-Beispiele vorhanden (Standard-Stil nutzen)."
        
        # 2. Bereite Fall-Daten vor
        fall_string = "\n".join([f"- {k}: {v}" for k, v in fall_daten.items()])
        
        # 3. Super Prompt zusammenbauen
        prompt = f"""
{self.system_prompt}

HIER IST WISSEN AUS DER KANZLEI-DATENBANK WIE WIR ÄHNLICHE FÄLLE BEARBEITET HABEN:
{rag_string}

================================

NEUER FALL FÜR DICH:
Notizen des Anwalts: {notizen}
Strukturierte Daten:
{fall_string}

AUFGABE:
Schreibe unter extremer Berücksichtigung der Beispiele im Wissen oben nun das perfekte Erstanschreiben für diesen neuen Fall. 
Erfinde keine Daten hinzu, die nicht im Fragebogen stehen. 
Gib NUR den Text des Anschreibens ohne Metakommentar zurück.
"""
        
        # 4. REST Call an Vertex AI (ohne SDK)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.2, # Niedrige Temperatur für sichere juristische Texte
                "maxOutputTokens": 2000
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                # Extrahiere den Text
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                    return candidates[0]["content"]["parts"][0].get("text", "")
                else:
                    logger.error(f"Unbekanntes API-Format: {data}")
                    return "Fehler bei der Textgenerierung (Format)."
                    
        except Exception as e:
            logger.error(f"Fehler beim Vertex/Gemini Call: {e}")
            return "Fehler bei der Kommunikation mit der Künstlichen Intelligenz."

# Singleton
orchestrator_service = OrchestratorService()
