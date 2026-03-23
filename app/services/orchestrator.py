from typing import Dict, Any, List
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_VERSICHERUNG = (
    "Du bist ein hochqualifizierter KI-Assistent für eine Anwaltskanzlei (Verkehrsrecht). "
    "Deine Aufgabe ist es, professionelle Erstanschreiben an gegnerische Versicherungen oder Schädiger zu entwerfen. "
    "WICHTIGE REGELN:\n"
    "- Kein Briefkopf, keine Absender-/Empfängeradressen, kein Datum, kein Betreff, "
    "KEINE Anrede, KEINE Grußformel — diese Teile werden vom System automatisch eingefügt.\n"
    "- Schreibe NUR den reinen Fließtext des Briefes (ab dem ersten inhaltlichen Satz).\n"
    "- Schreibe einen vollständigen, inhaltlich ausführlichen Brieftext.\n"
    "- Nutze zwingend den juristischen Tonfall und beachte folgende Vorgaben strikt:\n"
    "1. Zitiere immer die relevanten Anspruchsgrundlagen, insbesondere §§ 7, 18 StVG sowie § 115 VVG (Direktanspruch gegen die Haftpflichtversicherung).\n"
    "2. Setze für Zahlungs- oder Antwortaufforderungen standardmäßig eine Frist von 14 Tagen ab Zugang des Schreibens, sofern in den Notizen nichts anderes angegeben ist.\n"
    "3. Formuliere präzise Aufforderungen wie in den Beispielen, die dir als Kontext mitgegeben werden.\n"
    "4. Erfasse ALLE relevanten Schadenspositionen aus den Falldaten und fordere sie konkret ein."
)

SYSTEM_PROMPT_MANDANT = (
    "Du bist ein freundlicher KI-Assistent für eine Anwaltskanzlei (Verkehrsrecht). "
    "Deine Aufgabe ist es, ein Erstanschreiben an den eigenen Mandanten zu verfassen. "
    "WICHTIGE REGELN:\n"
    "- Kein Briefkopf, keine Absender-/Empfängeradressen, kein Datum, kein Betreff, "
    "KEINE Anrede, KEINE Grußformel — diese Teile werden vom System automatisch eingefügt.\n"
    "- Schreibe NUR den reinen Fließtext des Briefes (ab dem ersten inhaltlichen Satz).\n"
    "- Der Ton ist freundlich, verständlich und persönlich — KEIN juristischer Fachjargon, keine Paragraphen-Zitate.\n"
    "- Schreibe in der Wir-Form (die Kanzlei schreibt an den Mandanten).\n"
    "- Der Brief hat folgende feste Struktur (alle drei Punkte MÜSSEN enthalten sein):\n"
    "  1. Mandatsübernahme bestätigen: Wir haben Ihr Mandat übernommen und sind ab sofort für Sie tätig.\n"
    "  2. Maßnahmen zur Kenntnisnahme: Wir haben heute das Erstanschreiben an die gegnerische Versicherung versandt "
    "(beigefügt zur Kenntnisnahme). Den Inhalt kurz für den Mandanten zusammenfassen — verständlich, ohne Juristendeutsch.\n"
    "  3. Handlungsanweisung: Sollte sich die Versicherung oder eine andere Partei direkt an den Mandanten wenden, "
    "ist jede Kommunikation unbeantwortet an uns weiterzuleiten. Der Mandant soll sich auf keinen Fall selbst einlassen."
)


class OrchestratorService:
    """
    Baut Super-Prompts basierend auf RAG-Kontext zusammen und kommuniziert mit Gemini.
    """

    async def generate_draft(self, fall_daten: Dict[str, Any], notizen: str, rag_context: List[Dict[str, Any]], empfaenger_typ: str = 'versicherung') -> str:
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
        system_prompt = SYSTEM_PROMPT_MANDANT if empfaenger_typ == 'mandant' else SYSTEM_PROMPT_VERSICHERUNG
        aufgabe = (
            "Schreibe das Erstanschreiben an den Mandanten mit ALLEN drei Pflichtpunkten: "
            "1) Mandatsübernahme bestätigen, "
            "2) Kurze verständliche Zusammenfassung was wir an die Versicherung geschrieben haben (Anlage beifügen zur Kenntnisnahme), "
            "3) Handlungsanweisung: jede direkte Kontaktaufnahme durch Versicherung oder Gegner unbeantwortet an uns weiterleiten. "
            "Kein Fachjargon, keine Paragraphen. Gib NUR den Fließtext ohne Metakommentar zurück."
            if empfaenger_typ == 'mandant' else
            "Schreibe unter extremer Berücksichtigung der Beispiele im Wissen oben nun das perfekte Erstanschreiben für diesen neuen Fall. "
            "Erfinde keine Daten hinzu, die nicht im Fragebogen stehen. "
            "Gib NUR den Text des Anschreibens ohne Metakommentar zurück."
        )
        prompt = f"""
{system_prompt}

HIER IST WISSEN AUS DER KANZLEI-DATENBANK WIE WIR ÄHNLICHE FÄLLE BEARBEITET HABEN:
{rag_string}

================================

NEUER FALL FÜR DICH:
Notizen des Anwalts: {notizen}
Strukturierte Daten:
{fall_string}

AUFGABE:
{aufgabe}
"""
        
        # 4. REST Call an Vertex AI (ohne SDK)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.2, # Niedrige Temperatur für sichere juristische Texte
                "maxOutputTokens": 4096
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
                    
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Fehler beim Gemini Call: {e.response.status_code} - {e.response.text}")
            return f"Fehler bei der Kommunikation mit der Künstlichen Intelligenz (HTTP {e.response.status_code})."
        except Exception as e:
            logger.error(f"Fehler beim Vertex/Gemini Call: {e}")
            return "Fehler bei der Kommunikation mit der Künstlichen Intelligenz."
        return "Fehler bei der Textgenerierung."

# Singleton
orchestrator_service = OrchestratorService()
