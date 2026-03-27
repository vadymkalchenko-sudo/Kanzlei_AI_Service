"""
Query Service — MCP-Sekretärin (Task C2)

Verarbeitet Freitext-Anfragen via Gemini Function Calling und übersetzt sie
in strukturierte Django-API-Aufrufe. Gibt formatierte Ergebnisse zurück.

Ablauf:
  1. Freitext-Query empfangen
  2. Gemini Function Calling → Tool + Parameter bestimmen
  3. Django /api/ai/query/* Endpoint aufrufen
  4. Ergebnis für Frontend formatieren
"""
import httpx
import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

import re as _re_module


def _strip_markdown(text: str) -> str:
    """Entfernt Markdown-Formatierung aus LLM-Antworten (Post-Processing-Fallback)."""
    # **bold** → bold
    text = _re_module.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # *italic* → italic
    text = _re_module.sub(r'\*(.+?)\*', r'\1', text)
    # ## Überschriften → Text
    text = _re_module.sub(r'^#{1,6}\s+', '', text, flags=_re_module.MULTILINE)
    # - oder * Aufzählungszeichen am Zeilenanfang entfernen
    text = _re_module.sub(r'^[-*]\s+', '', text, flags=_re_module.MULTILINE)
    return text


# ===========================================================================
# TOOL-DEFINITIONEN für Gemini Function Calling
# ===========================================================================

TOOL_DECLARATIONS: List[Dict] = [
    {
        "name": "get_akten_liste",
        "description": (
            "Liste aller Akten (Rechtsfälle) abrufen. "
            "Kann nach Status, Monat, Jahr und Sachbearbeiter gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Aktenstatus: 'Offen', 'Geschlossen' oder 'Archiviert'",
                },
                "monat": {
                    "type": "integer",
                    "description": "Monat (1–12), bezieht sich auf erstellt_am",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
                "sachbearbeiter": {
                    "type": "string",
                    "description": "Name des Sachbearbeiters/Referenten (Teilstring-Suche)",
                },
            },
        },
    },
    {
        "name": "get_offene_betraege",
        "description": (
            "Offene (noch nicht bezahlte) Zahlungspositionen mit Soll- und Habenbeträgen abrufen. "
            "Kann nach Monat und Jahr gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "monat": {
                    "type": "integer",
                    "description": "Monat (1–12)",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
            },
        },
    },
    {
        "name": "count_faelle",
        "description": (
            "Anzahl der Fälle (Akten) zählen, optional gefiltert nach Sachbearbeiter, Jahr und Status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sachbearbeiter": {
                    "type": "string",
                    "description": "Name des Sachbearbeiters/Referenten (Teilstring-Suche)",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
                "status": {
                    "type": "string",
                    "description": "Aktenstatus: 'Offen', 'Geschlossen' oder 'Archiviert'",
                },
            },
        },
    },
    {
        "name": "get_akten_ohne_fragebogen",
        "description": (
            "Alle Akten abrufen, bei denen noch kein Fragebogen ausgefüllt wurde "
            "(fehlende Unfalldetails, Daten unvollständig)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_fristen_naechste_tage",
        "description": (
            "Alle offenen Fristen (Deadlines) abrufen, die in den nächsten N Tagen ablaufen. "
            "Standard: 30 Tage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tage": {
                    "type": "integer",
                    "description": "Anzahl der Tage voraus (Standard: 30)",
                },
            },
        },
    },
    {
        "name": "get_akte_by_aktenzeichen",
        "description": "Eine bestimmte Akte anhand ihres Aktenzeichens (z.B. '01.26.XYZ') abrufen.",
        "parameters": {
            "type": "object",
            "properties": {
                "aktenzeichen": {
                    "type": "string",
                    "description": "Das Aktenzeichen der gesuchten Akte",
                },
            },
            "required": ["aktenzeichen"],
        },
    },
    {
        "name": "get_akten_by_empfehlung",
        "description": (
            "Akten abrufen, deren Mandant über eine bestimmte Empfehlung/Quelle kam. "
            "Z.B. 'Wie viele Akten wurden im März auf Empfehlung von Max geöffnet?' "
            "Kann nach Monat und Jahr gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "empfehlung": {
                    "type": "string",
                    "description": "Name oder Quelle der Empfehlung (Teilstring-Suche), z.B. 'Max', 'Google Ads'",
                },
                "monat": {
                    "type": "integer",
                    "description": "Monat (1–12)",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
            },
            "required": ["empfehlung"],
        },
    },
    {
        "name": "get_akten_ohne_dokument",
        "description": (
            "Akten abrufen, die ein bestimmtes Dokument NICHT enthalten. "
            "Z.B. Akten ohne Erstanschreiben, ohne Klageschrift, ohne Vollmacht. "
            "Kann zusätzlich nach Gegner (Versicherung) und Status gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dokument_stichwort": {
                    "type": "string",
                    "description": "Stichwort im Dokumenttitel, z.B. 'Erstanschreiben', 'Vollmacht', 'Klageschrift'",
                },
                "gegner": {
                    "type": "string",
                    "description": "Name der Gegnerpartei/Versicherung (Teilstring), z.B. 'MDT', 'HUK', 'Allianz'",
                },
                "status": {
                    "type": "string",
                    "description": "Aktenstatus: 'Offen', 'Geschlossen' oder 'Archiviert'",
                },
            },
            "required": ["dokument_stichwort"],
        },
    },
    {
        "name": "get_akten_by_gegner",
        "description": (
            "Alle Akten einer bestimmten Gegnerpartei oder Versicherung abrufen. "
            "Z.B. alle Fälle gegen MDT, HUK, Allianz."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gegner": {
                    "type": "string",
                    "description": "Name der Gegnerpartei/Versicherung (Teilstring-Suche), z.B. 'MDT', 'HUK'",
                },
            },
            "required": ["gegner"],
        },
    },
    {
        "name": "erstelle_brief_aus_kontext",
        "description": "Erstellt einen professionellen Brieftext wenn der User einen Text/Begründung eingibt und daraus einen Brief formuliert haben möchte.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_kontext": {
                    "type": "string",
                    "description": "Der vom User eingefügte Text / die Begründung"
                },
                "schreiben_typ": {
                    "type": "string",
                    "description": "widerspruch | anfrage | mahnung | sonstig"
                }
            },
            "required": ["user_kontext"],
        },
    },
    {
        "name": "sync_frist_zu_calendar",
        "description": (
            "Synchronisiert eine Frist oder Aufgabe in Google Calendar. "
            "Wenn der User sagt: 'Leg die Frist in den Kalender' oder "
            "'Widerspruchsfrist am 15.04. eintragen'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "akte_id": {
                    "type": "integer",
                    "description": "ID der Akte"
                },
                "titel": {
                    "type": "string",
                    "description": "Titel, z.B. 'Widerspruchsfrist'"
                },
                "datum": {
                    "type": "string",
                    "description": "Datum im Format YYYY-MM-DD"
                },
                "beschreibung": {
                    "type": "string",
                    "description": "Optionale Beschreibung"
                },
            },
            "required": ["akte_id", "titel", "datum"],
        }
    },
    {
        "name": "sende_email_an_gegner",
        "description": (
            "Sendet eine E-Mail an den Gegner (z.B. Versicherung) der aktuellen Akte. "
            "Wenn der User sagt: 'Schick das an die Allianz' oder "
            "'E-Mail an den Gegner mit dem Widerspruch'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "akte_id": {
                    "type": "integer",
                    "description": "ID der Akte"
                },
                "betreff": {
                    "type": "string",
                    "description": "E-Mail-Betreff"
                },
                "text": {
                    "type": "string",
                    "description": "E-Mail-Text (Fliesstext)"
                },
                "dokument_id": {
                    "type": "integer",
                    "description": "Optional: ID des anzuhängenden Dokuments"
                },
            },
            "required": ["akte_id", "betreff", "text"],
        }
    }
]


# ===========================================================================
# HILFSFUNKTIONEN
# ===========================================================================

def _tab_hinweis(active_tab: str) -> str:
    hinweise = {
        "dokumente": "Fokus: Dokumente — Inhalte erklären, PDF-Umwandlung vorschlagen.",
        "finanzen":  "Fokus: Finanzen — RVG-Berechnung, Zahlungspositionen, offene Beträge.",
        "uebersicht": "Fokus: Kurzer Statusüberblick, nächster offener Schritt.",
        "ki":        "Fokus: Vollständige Workflow-Unterstützung — Analyse, Briefe, Aktionen.",
    }
    return hinweise.get(active_tab, "")


# ===========================================================================
# QUERY SERVICE
# ===========================================================================

class QueryService:
    """
    Verarbeitet Freitext-Anfragen via Gemini Function Calling
    und ruft die entsprechenden Django /api/ai/query/* Endpoints auf.
    """

    def __init__(self):
        self.django_base = settings.backend_url.rstrip("/")
        self.django_headers = {
            "Authorization": f"Bearer {settings.backend_api_token}",
            "Content-Type": "application/json",
        }

    async def handle_query(self, query: str, user_id: int, akte_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Haupteinstiegspunkt: Freitext → Gemini/Vertex → Tool-Call → Django → formatiertes Ergebnis.
        """
        from app.main import get_gemini_client
        if not get_gemini_client():
            return {"status": "error", "error": "KI-Dienst nicht bereit."}

        # cast for pyre
        safe_query = str(query) if query else ""
        logger.info(f"QueryService: Verarbeite Anfrage von User {user_id}: '{safe_query[:80]}'")

        # 1. Gemini Function Calling → Tool + Parameter bestimmen
        function_call = await self._classify_with_gemini(query)

        if not function_call:
            logger.info("Kein Tool gewählt -> Fallback auf System-Wissen RAG")
            return await self._handle_rag_fallback(query)

        tool_name = str(function_call.get("name", ""))
        tool_args = function_call.get("args", {})
        logger.info(f"Gemini wählte Tool: {tool_name}, Args: {tool_args}")

        # 2. Django-Endpoint aufrufen
        raw_data = await self._execute_tool(tool_name, tool_args, akte_id)

        if raw_data is None:
            return {
                "status": "error",
                "error": f"Datenbankabfrage für '{tool_name}' fehlgeschlagen.",
            }

        if not isinstance(raw_data, dict) and not isinstance(raw_data, list):
            return {
                "status": "error",
                "error": f"Ungültiges Rückgabeformat für '{tool_name}'.",
            }

        # 3. Ergebnis für Frontend aufbereiten
        return self._format_result(tool_name, raw_data)

    # -----------------------------------------------------------------------
    # Gemini Function Calling
    # -----------------------------------------------------------------------

    async def _classify_with_gemini(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Sendet die Anfrage an Gemini/Vertex mit Function Calling (neues SDK).
        Gibt den gewählten Tool-Call zurück oder None wenn kein Tool passt.
        """
        from app.main import get_gemini_client
        from google.genai import types as genai_types

        gemini = get_gemini_client()
        if not gemini:
            return None

        system_text = (
            "Du bist eine KI-Sekretärin für eine Kanzlei (Verkehrsrecht). "
            "Analysiere die Anfrage und wähle das passende Werkzeug aus. "
            "Wähle genau ein Werkzeug. Wenn keine Anfrage zu den Werkzeugen passt, "
            "antworte ohne Werkzeug-Aufruf."
        )

        config = genai_types.GenerateContentConfig(
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            system_instruction=system_text,
            temperature=0.0,
        )

        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=query,
                config=config,
            )

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        return {"name": fc.name, "args": dict(fc.args)}

            logger.info("Gemini hat kein Tool gewählt (kein passender Befehl).")
            return None

        except Exception as e:
            logger.error(f"Gemini Function Calling Fehler: {e}")
            return None

    async def _handle_rag_fallback(self, query: str) -> Dict[str, Any]:
        """Sucht im system_wissen via RAG und generiert eine Antwort mit Gemini."""
        from app.services.rag_store import rag_store
        
        # 1. RAG-Abfrage in der System-Doku
        matches = await rag_store.search_similar(query_text=query, n_results=3, collection_name="system_wissen")
        
        if not matches:
            return {
                "status": "ok",
                "result_type": "text",
                "data": (
                    "Ich konnte die Anfrage leider keinem meiner Werkzeuge zuordnen "
                    "und habe dazu auch keine Informationen in meiner System-Doku gefunden. "
                    "Versuche es mit einer spezifischeren Frage."
                ),
                "query_used": "fallback",
            }
            
        # 2. Kontext zusammenbauen
        context_texts = []
        for match in matches:
            context_texts.append(match.get("text", ""))
        context_str = "\n\n---\n\n".join(context_texts)
        
        # 3. Antwort via neuem SDK generieren (Vertex AI oder Gemini)
        from app.main import get_gemini_client
        from google.genai import types as genai_types

        gemini = get_gemini_client()
        if not gemini:
            return {"status": "error", "error": "KI-Dienst nicht bereit."}

        system_prompt = (
            "Du bist ein hilfreicher Assistent für das Kanzlei-Programm. "
            "Beantworte die Frage des Nutzers AUSSCHLIESSLICH basierend auf dem folgenden System-Wissen. "
            "Erfinde keine Funktionen hinzu. Halte dich kurz und prägnant."
        )
        prompt = f"SYSTEM-WISSEN:\n{context_str}\n\nFRAGE DES NUTZERS:\n{query}"

        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                ),
            )
            answer_text = response.text.strip() if response.text else ""
            if answer_text:
                return {
                    "status": "ok",
                    "result_type": "text",
                    "data": answer_text,
                    "query_used": "rag_system_wissen",
                }
            return {"status": "error", "error": "Konnte keine Antwort aus dem System-Wissen generieren."}
        except Exception as e:
            logger.error(f"Fehler bei der Fallback-Antwort Generierung: {e}")
            return {"status": "error", "error": "Fehler bei der Formulierung der System-Antwort."}

    # -----------------------------------------------------------------------
    # Tool-Dispatch → Django /api/ai/query/* Endpoints
    # -----------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, args: Dict[str, Any], akte_id: Optional[int] = None) -> Optional[Any]:
        """Routet den Tool-Call zum passenden Django-Endpoint."""
        tool_map = {
            "get_akten_liste": self._get_akten_liste,
            "get_offene_betraege": self._get_offene_betraege,
            "count_faelle": self._count_faelle,
            "get_akten_ohne_fragebogen": self._get_akten_ohne_fragebogen,
            "get_fristen_naechste_tage": self._get_fristen_naechste_tage,
            "get_akte_by_aktenzeichen": self._get_akte_by_aktenzeichen,
            "get_akten_by_empfehlung": self._get_akten_by_empfehlung,
            "get_akten_ohne_dokument": self._get_akten_ohne_dokument,
            "get_akten_by_gegner": self._get_akten_by_gegner,
            "erstelle_brief_aus_kontext": self._erstelle_brief_aus_kontext,
            "sync_frist_zu_calendar": self._sync_frist_zu_calendar,
            "sende_email_an_gegner": self._sende_email_an_gegner,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            logger.warning(f"Unbekanntes Tool: {tool_name}")
            return None

        try:
            if tool_name == "erstelle_brief_aus_kontext":
                # Empfänger und Notizen optional durchschleifen, wenn sie im Request sind
                empfaenger = args.pop('empfaenger', 'versicherung')
                notizen = args.pop('notizen', '')
                # type: ignore (Pyre2: Typensignatur von handler ist dynamisch)
                return await handler(
                    user_kontext=args.get('user_kontext', ''),
                    schreiben_typ=args.get('schreiben_typ'),
                    akte_id=akte_id,
                    empfaenger=empfaenger,
                    notizen=notizen
                )
            return await handler(**args)  # type: ignore
        except Exception as e:
            logger.error(f"Tool-Ausführung fehlgeschlagen ({tool_name}): {e}")
            return None

    async def _get(self, path: str, params: Dict = None) -> Any:
        """Hilfsfunktion: GET-Request an Django /api/ai/query/ mit Bearer-Token."""
        url = f"{self.django_base}/api/ai/query/{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url, params=params or {}, headers=self.django_headers
            )
            response.raise_for_status()
            return response.json()

    async def _get_akten_liste(
        self,
        status: str = None,
        monat: int = None,
        jahr: int = None,
        sachbearbeiter: str = None,
    ):
        params = {}
        if status:
            params["status"] = status
        if monat:
            params["monat"] = monat
        if jahr:
            params["jahr"] = jahr
        if sachbearbeiter:
            params["sachbearbeiter"] = sachbearbeiter
        return await self._get("akten/", params)

    async def _get_offene_betraege(self, monat: int = None, jahr: int = None):
        params = {}
        if monat:
            params["monat"] = monat
        if jahr:
            params["jahr"] = jahr
        return await self._get("offene_betraege/", params)

    async def _count_faelle(
        self,
        sachbearbeiter: str = None,
        jahr: int = None,
        status: str = None,
    ):
        params = {}
        if sachbearbeiter:
            params["sachbearbeiter"] = sachbearbeiter
        if jahr:
            params["jahr"] = jahr
        if status:
            params["status"] = status
        return await self._get("count_faelle/", params)

    async def _get_akten_ohne_fragebogen(self):
        return await self._get("akten_ohne_fragebogen/")

    async def _get_fristen_naechste_tage(self, tage: int = 30):
        return await self._get("fristen/", {"tage": tage})

    async def _get_akte_by_aktenzeichen(self, aktenzeichen: str):
        return await self._get("akte_by_az/", {"aktenzeichen": aktenzeichen})

    async def _get_akten_ohne_dokument(self, dokument_stichwort: str, gegner: str = None, status: str = None):
        params = {"dokument_stichwort": dokument_stichwort}
        if gegner: params["gegner"] = gegner
        if status: params["status"] = status
        return await self._get("akten_ohne_dokument/", params)

    async def _get_akten_by_gegner(self, gegner: str):
        return await self._get("akten_by_gegner/", {"gegner": gegner})

    async def _get_akten_by_empfehlung(self, empfehlung: str, monat: int = None, jahr: int = None):
        params = {"empfehlung": empfehlung}
        if monat: params["monat"] = monat
        if jahr: params["jahr"] = jahr
        return await self._get("akten_by_empfehlung/", params)

    async def _erstelle_brief_aus_kontext(
        self, 
        user_kontext: str, 
        schreiben_typ: str = None, 
        akte_id: int = None,
        empfaenger: str = 'versicherung',
        notizen: str = ''
    ):
        """
        N-G2 Tool Handler: Generiert einen Brief-Rohtext direkt hier im AI-Service.
        Erweitert um Akte-Daten via RAG.
        """
        from app.main import get_gemini_client
        gemini = get_gemini_client()
        if not gemini:
            return {"error": "Gemini API nicht bereit", "brief_text": "Lokale Generierung nicht möglich."}
        
        akte_context = ""
        rag_context = ""

        if akte_id:
            try:
                akte_data = await self._get("akte_by_id/", {"akte_id": akte_id})
                akte_context = (
                    f"Akte-Details:\n"
                    f"Aktenzeichen: {akte_data.get('aktenzeichen')}\n"
                    f"Mandant: {akte_data.get('mandant')}\n"
                    f"Gegner: {akte_data.get('gegner')}\n"
                    f"Unfallort: {akte_data.get('unfallort', getattr(akte_data, 'unfallort', ''))}\n"
                )
            except Exception as e:
                logger.warning(f"Konnte Akte {akte_id} Context nicht laden: {e}")

            try:
                from app.services.rag_store import rag_store
                matches = await rag_store.search_similar(user_kontext, n_results=3, collection_name="muster_schreiben")
                if matches:
                    muster_texts = [m.get("text", "") for m in matches]
                    rag_context = "Hier sind ähnliche Muster-Schreiben als Stil-Referenz:\n" + "\n---\n".join(muster_texts)
            except Exception as e:
                logger.warning(f"RAG-Suche in muster_schreiben fehlgeschlagen: {e}")
            
        system_instruction = (
            "Du bist ein erfahrener Rechtsanwalt. Formuliere einen professionellen "
            "Brieftext basierend auf dem vom Benutzer bereitgestellten Kontext.\n\n"
            "WICHTIG: Generiere NUR den Fließtext des Briefes — OHNE Anrede und OHNE Grußformel.\n"
            "KEIN Briefkopf, KEINE Adresse, KEIN Datum, KEIN Aktenzeichen, KEINE Anrede ('Sehr geehrte...').\n"
            "Anrede, Briefkopf und Signatur werden vom System automatisch ergänzt.\n"
            "Halte den rechtlichen Ton professionell und präzise."
        )
        
        prompt_parts = []
        if empfaenger == 'mandant':
             prompt_parts.append("EMPFEÄNGER-KONTEXT: Das Schreiben ist eine Sachstandsinformation an den Mandanten.")
        else:
             prompt_parts.append("EMPFEÄNGER-KONTEXT: Das Schreiben geht an die gegnerische Versicherung/Haftpflicht.")

        if akte_context:
            prompt_parts.append(f"AKTE-KONTEXT:\n{akte_context}")
        if rag_context:
            prompt_parts.append(f"MUSTER-VORLAGEN (zur Orientierung für Struktur/Formulierung):\n{rag_context}")
        
        prompt_parts.append(f"VORGABE / USER-KONTEXT:\n{user_kontext}")
        if notizen:
            prompt_parts.append(f"Besondere Hinweise des Sachbearbeiters:\n{notizen}")

        prompt_parts.append(f"SCHREIBEN-TYP:\n{schreiben_typ or 'Allgemein'}")
        prompt_parts.append("Bitte generiere jetzt den Brieftext (nur Fließtext).")

        prompt = "\n\n".join(prompt_parts)
        
        import asyncio
        full_prompt = f"{system_instruction}\n\n{prompt}"
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(None, gemini.generate, full_prompt)
        
        return {
            "brief_text": response_text.strip(),
            "schreiben_typ": schreiben_typ or "sonstig"
        }

    async def _sync_frist_zu_calendar(self, akte_id: int, titel: str, datum: str, beschreibung: str = ""):
        """N-G3 Tool Handler: Erstellt ein Google Calendar Event"""
        from app.services.google_calendar_client import google_calendar_client
        import datetime
        
        try:
            parsed_date = datetime.date.fromisoformat(datum)
        except ValueError:
            return {"error": f"Ungültiges Datumsformat: {datum}. Erwartet: YYYY-MM-DD"}
            
        event_id = google_calendar_client.create_event(
            titel=titel,
            datum=parsed_date,
            beschreibung=beschreibung,
            akte_id=akte_id
        )
        
        if event_id:
            return {
                "status": "success",
                "event_id": event_id,
                "datum": datum
            }
        else:
            return {
                "status": "mock",
                "message": "Google Calendar nicht konfiguriert."
            }

    async def _sende_email_an_gegner(self, akte_id: int, betreff: str, text: str, dokument_id: int = None):
        """GM-2 Tool Handler: Sendet eine E-Mail an den Gegner."""
        from app.services.google_gmail_client import google_gmail_client
        
        # 1. Gegner E-Mail aus Akte laden (Wir nutzen den bestehenden /akte_by_id/ API-Pfad 
        #    bzw. passen die Abfrage soweit nötig an. In Aufgabe wurde erwähnt:
        #    'GET /api/ai/query/akte_by_id/?akte_id=...' -> wir nehmen _get)
        try:
            # Versuche Akte per ID zu laden. Wenn der Endpoint noch nicht existiert,
            # fangen wir den Fehler ab und geben einen sauberen Hinweis.
            try:
                akte_data = await self._get("akte_by_id/", {"akte_id": akte_id})
            except Exception as e:
                logger.error(f"Konnte Akte {akte_id} nicht über akte_by_id/ laden: {e}")
                return {"error": f"Informationen zur Akte {akte_id} konnten zur Zeit nicht geladen werden (Endpoint fehlt?)."}
                
            gegner_email = akte_data.get("gegner_email")
            if not gegner_email:
                # Falls keine Email da ist
                return {"error": f"Keine E-Mail-Adresse für den Gegner von Akte {akte_id} hinterlegt."}
                
            erfolg = google_gmail_client.send_email(
                an=gegner_email,
                betreff=betreff,
                text=text
            )
            
            if erfolg:
                return {
                    "status": "success",
                    "an": gegner_email,
                    "betreff": betreff
                }
            elif not google_gmail_client.enabled:
                return {
                    "status": "mock",
                    "message": "Gmail nicht konfiguriert — E-Mail nicht gesendet."
                }
            else:
                 return {"error": "Senden der E-Mail fehlgeschlagen."}
                 
        except Exception as e:
            logger.error(f"Fehler in _sende_email_an_gegner: {e}")
            return {"error": str(e)}

    # -----------------------------------------------------------------------
    # Ergebnis-Formatierung → Frontend-Format
    # -----------------------------------------------------------------------

    def _format_result(self, tool_name: str, raw_data: Any) -> Dict[str, Any]:
        """Wandelt Django-Rohdaten in das Frontend-kompatible Format um."""

        if tool_name == "count_faelle":
            return {
                "status": "ok",
                "result_type": "number",
                "data": raw_data.get("count", 0),
                "label": raw_data.get("label", "Fälle"),
                "query_used": tool_name,
            }

        if tool_name == "erstelle_brief_aus_kontext":
            return {
                "status": "ok",
                "result_type": "brief_aus_kontext",
                "data": raw_data.get("brief_text"),
                "schreiben_typ": raw_data.get("schreiben_typ"),
                "query_used": tool_name,
            }
            
        if tool_name == "sync_frist_zu_calendar":
            if raw_data.get("status") == "success":
                return {
                    "status": "ok",
                    "result_type": "calendar_event_erstellt",
                    "data": {
                        "event_id": raw_data.get("event_id"),
                        "datum": raw_data.get("datum")
                    },
                    "query_used": tool_name,
                }
            elif raw_data.get("status") == "mock":
                return {
                    "status": "ok",
                    "result_type": "info",
                    "data": raw_data.get("message"),
                    "query_used": tool_name,
                }
            else:
                return {
                    "status": "error",
                    "result_type": "text",
                    "data": raw_data.get("error", "Unbekannter Fehler bei Calendar-Sync"),
                    "query_used": tool_name,
                }
                
        if tool_name == "sende_email_an_gegner":
            if raw_data.get("status") == "success":
                return {
                    "status": "ok",
                    "result_type": "email_gesendet",
                    "data": {
                        "an": raw_data.get("an"),
                        "betreff": raw_data.get("betreff")
                    },
                    "query_used": tool_name,
                }
            elif raw_data.get("status") == "mock":
                return {
                    "status": "ok",
                    "result_type": "info",
                    "data": raw_data.get("message"),
                    "query_used": tool_name,
                }
            else:
                 return {
                    "status": "error",
                    "result_type": "fehler",
                    "data": raw_data.get("error", "Konnte E-Mail nicht senden."),
                    "query_used": tool_name,
                }

        if tool_name == "get_akte_by_aktenzeichen":
            akte = raw_data.get("akte")
            if not akte:
                return {
                    "status": "ok",
                    "result_type": "text",
                    "data": "Keine Akte mit diesem Aktenzeichen gefunden.",
                    "query_used": tool_name,
                }
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Aktenzeichen", "Mandant", "Gegner", "Status"],
                "data": [[akte["aktenzeichen"], akte["mandant"], akte["gegner"], akte["status"]]],
                "query_used": tool_name,
            }

        if tool_name in ("get_akten_liste", "get_akten_ohne_fragebogen", "get_akten_ohne_dokument", "get_akten_by_gegner"):
            akten = raw_data.get("akten", [])
            rows = [
                [a["aktenzeichen"], a["mandant"], a["gegner"], a["status"], a.get("erstellt_am", "")]
                for a in akten
            ]
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Aktenzeichen", "Mandant", "Gegner", "Status", "Erstellt"],
                "data": rows,
                "total": len(rows),
                "query_used": tool_name,
            }

        if tool_name == "get_offene_betraege":
            positionen = raw_data.get("positionen", [])
            rows = [
                [
                    p["akte_az"],
                    p["beschreibung"],
                    f'{p["soll_betrag"]} €',
                    f'{p["haben_betrag"]} €',
                    p["status"],
                ]
                for p in positionen
            ]
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Akte", "Beschreibung", "Soll", "Haben", "Status"],
                "data": rows,
                "total": raw_data.get("gesamt_offen", 0),
                "total_label": "Gesamtbetrag offen (€)",
                "query_used": tool_name,
            }

        if tool_name == "get_fristen_naechste_tage":
            fristen = raw_data.get("fristen", [])
            rows = [
                [f["bezeichnung"], f["akte_az"], f["frist_datum"], f.get("prioritaet", "")]
                for f in fristen
            ]
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Frist", "Akte", "Fällig am", "Priorität"],
                "data": rows,
                "total": len(rows),
                "query_used": tool_name,
            }

        # Fallback
        return {
            "status": "ok",
            "result_type": "text",
            "data": str(raw_data),
            "query_used": tool_name,
        }

    # -----------------------------------------------------------------------
    # LOKI CHAT — Multi-Turn Function Calling
    # -----------------------------------------------------------------------

    async def _execute_chat_tool(self, tool_name: str, args: dict) -> dict:
        from app.services.hmac_auth import generate_ki_signature
        headers = {"X-KI-Signature": generate_ki_signature()}

        def _safe_json(resp) -> dict:
            """Gibt resp.json() zurück oder einen Fehler-Dict bei HTTP-Fehler / Parse-Fehler."""
            try:
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"_execute_chat_tool HTTP {e.response.status_code} für {tool_name}: {e.response.text[:200]}")
                return {"error": f"Backend-Fehler {e.response.status_code}"}
            except Exception as e:
                logger.error(f"_execute_chat_tool JSON-Parse-Fehler für {tool_name}: {e}")
                return {"error": "Unerwartete Backend-Antwort"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if tool_name == "get_finanzdaten":
                    resp = await client.get(
                        f"{self.django_base}/api/ai/query/finanzdaten/",
                        params={"akte_id": args["akte_id"]},
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "erstelle_aufgabe":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_aufgabe/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "erstelle_frist":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_frist/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "aendere_aktenstatus":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/aendere_aktenstatus/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "berechne_rvg":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/berechne_rvg/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "erstelle_brief":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_brief/",
                        json={
                            "akte_id": args["akte_id"],
                            "brief_text": args.get("brief_text", ""),
                            "betreff": args.get("betreff", ""),
                            "empfaenger": args.get("empfaenger", "versicherung"),
                        },
                        headers=headers
                    )
                    result = _safe_json(resp)
                    # AUTO ki_memory: direkt nach erfolgreichem Brief speichern (nicht auf Loki warten)
                    if resp.status_code in (200, 201) and "error" not in result:
                        from datetime import datetime as _now_dt
                        datum_mem = _now_dt.now().strftime("%d.%m.%Y")
                        empf_label = "Vers." if args.get("empfaenger", "versicherung") == "versicherung" else "Mdt."
                        betreff_mem = str(args.get("betreff", ""))
                        auszug = str(args.get("brief_text", ""))[0:400]  # type: ignore[index]
                        eintrag = f"Brief an {empf_label} (Betreff: {betreff_mem}): {auszug}"
                        mem_get = await client.get(
                            f"{self.django_base}/api/cases/akten/{args['akte_id']}/ki_memory/",
                            headers=headers
                        )
                        current_mem = mem_get.json().get("ki_memory", "") if mem_get.status_code == 200 else ""
                        new_mem = f"{current_mem}\n[{datum_mem}] {eintrag}".strip()
                        await client.post(
                            f"{self.django_base}/api/cases/akten/{args['akte_id']}/ki_memory/",
                            json={"ki_memory": new_mem},
                            headers=headers
                        )
                        logger.info(f"AUTO ki_memory Brief für Akte {args['akte_id']}: {eintrag[0:80]}")  # type: ignore[index]
                    return result

                elif tool_name == "erstelle_zahlungspositionen":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_zahlungspositionen/",
                        json={
                            "akte_id": args["akte_id"],
                            "positionen": args.get("positionen", []),
                        },
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "buche_zahlung":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/buche_zahlung/",
                        json={
                            "zahlungsposition_id": args["zahlungsposition_id"],
                            "haben_betrag": args["haben_betrag"],
                        },
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "aktualisiere_ki_memory":
                    akte_id_mem = args["akte_id"]
                    eintrag = args.get("eintrag", "").strip()
                    # Aktuellen Stand laden und neuen Eintrag anhängen
                    get_resp = await client.get(
                        f"{self.django_base}/api/cases/akten/{akte_id_mem}/ki_memory/",
                        headers=headers
                    )
                    current = get_resp.json().get("ki_memory", "") if get_resp.status_code == 200 else ""
                    from datetime import datetime
                    datum = datetime.now().strftime("%d.%m.%Y")
                    new_memory = f"{current}\n[{datum}] {eintrag}".strip()
                    resp = await client.post(
                        f"{self.django_base}/api/cases/akten/{akte_id_mem}/ki_memory/",
                        json={"ki_memory": new_memory},
                        headers=headers
                    )
                    if resp.status_code in (200, 201):
                        logger.info(f"ki_memory angehängt für Akte {akte_id_mem}: {eintrag[:80]}")
                        return {"status": "gespeichert"}
                    return {"error": f"ki_memory Fehler {resp.status_code}"}

            return {"error": f"Unbekanntes Tool: {tool_name}"}

        except httpx.TimeoutException:
            logger.error(f"_execute_chat_tool Timeout bei Tool: {tool_name}")
            return {"error": f"Timeout bei Ausführung von '{tool_name}' — Backend nicht erreichbar."}
        except Exception as e:
            logger.error(f"_execute_chat_tool unerwarteter Fehler ({tool_name}): {e}", exc_info=True)
            return {"error": f"Interner Fehler bei '{tool_name}': {str(e)}"}

    async def _erkenne_falltyp(self, kontext: dict, ki_memory: str) -> str:
        """
        Bestimmt den Falltyp aus Akten-Kontext.
        Reihenfolge: ki_memory > fragebogen > Gegner/Ziel-Text > Heuristik
        """
        # 1. Bereits im ki_memory gespeichert?
        if ki_memory:
            for line in ki_memory.lower().split("\n"):
                if "falltyp:" in line:
                    return line.split("falltyp:", 1)[-1].strip().split()[0]

        # 2. Fragebogen vorhanden?
        fragebogen = kontext.get("fragebogen", {})
        if isinstance(fragebogen, dict) and fragebogen:
            if fragebogen.get("personenschaden"):
                return "personenschaden"
            # Unfallakte: Unfalldatum oder Kennzeichen vorhanden
            if fragebogen.get("datum_zeit") or fragebogen.get("gegner_kennzeichen"):
                return "verkehrsunfall_haftpflicht"

        # 3. Schlüsselwörter in Ziel/Gegner
        text = f"{kontext.get('ziel', '')} {kontext.get('gegner', '')}".lower()
        if any(w in text for w in ["haftpflicht", "unfall", "versicherung", "schadensregulierung", "stvg", "vvg"]):
            return "verkehrsunfall_haftpflicht"
        if any(w in text for w in ["personenschaden", "schmerzensgeld", "verletzung", "behandlung"]):
            return "personenschaden"

        return "unbekannt"

    async def _lade_workflow_kontext(self, falltyp: str) -> str:
        """
        Lädt das passende Workflow-Dokument aus RAG system_wissen.
        Gibt leeren String zurück wenn kein Treffer oder Fehler.
        """
        if falltyp == "unbekannt":
            return ""
        try:
            from app.services.rag_store import rag_store
            query = f"Workflow Ablauf Stufen {falltyp.replace('_', ' ')}"
            matches = await rag_store.search_similar(
                query_text=query,
                n_results=4,
                filter_dict={"typ": "system_doku"},
                collection_name="system_wissen",
            )
            if not matches:
                return ""
            return "\n---\n".join(m.get("text", m.get("document", "")) for m in matches)
        except Exception as e:
            logger.warning(f"_lade_workflow_kontext Fehler ({falltyp}): {e}")
            return ""

    async def handle_akte_chat(
        self,
        akte_id: int,
        messages: list[dict],
        kontext: dict,
        ki_memory: str = "",
        active_tab: str = "ki",
    ) -> dict:
        from app.main import get_gemini_client
        gemini = get_gemini_client()
        if not gemini:
            return {"reply": "Gemini API nicht bereit", "actions_taken": []}

        # Finanzdaten lesbar formatieren
        finanzdaten_raw = kontext.get('finanzdaten', [])
        if finanzdaten_raw:
            gesamt_soll = sum(p.get('soll', 0) for p in finanzdaten_raw)
            gesamt_haben = sum(p.get('haben', 0) for p in finanzdaten_raw)
            fd_lines = []
            for p in finanzdaten_raw:
                zp_id = p.get('id', '?')
                cat = p.get('category', '–')
                beschr = p.get('beschreibung', '–')
                soll = p.get('soll', 0)
                haben = p.get('haben', 0)
                st = p.get('status', '–')
                fd_lines.append(f"  [ID:{zp_id}][{cat}] {beschr}: Forderung={soll:.2f}€, Erhalten={haben:.2f}€, Status={st}")
            fd_lines.append(f"  → GESAMT: Forderung={gesamt_soll:.2f}€, Erhalten={gesamt_haben:.2f}€, Noch offen={gesamt_soll - gesamt_haben:.2f}€")
            finanzdaten_text = "\n".join(fd_lines)
        else:
            finanzdaten_text = "Keine Finanzdaten vorhanden."

        # Aufgaben lesbar formatieren
        aufgaben_raw = kontext.get('aufgaben', [])
        aufgaben_text = "\n".join(
            f"  - {a.get('titel', '?')} (Status: {a.get('status', '?')}, Fällig: {a.get('faellig_am', 'k.A.')})"
            for a in aufgaben_raw
        ) if aufgaben_raw else "Keine offenen Aufgaben."

        # Fristen lesbar formatieren
        fristen_raw = kontext.get('fristen', [])
        fristen_text = "\n".join(
            f"  - {f.get('bezeichnung', '?')} am {f.get('frist_datum', '?')} [Priorität: {f.get('prioritaet', '?')}, Erledigt: {f.get('erledigt', False)}]"
            for f in fristen_raw
        ) if fristen_raw else "Keine Fristen vorhanden."

        # Dokumente lesbar formatieren
        dokumente_raw = kontext.get('dokumente', [])
        dokumente_text = "\n".join(
            f"  - [{d.get('kategorie', '–')}] {d.get('titel', '?')} (Datum: {d.get('datum', 'k.A.')})"
            for d in dokumente_raw
        ) if dokumente_raw else "Keine Dokumente vorhanden."

        # Generierte Briefe (KI-erstellte Schreiben) mit Inhalt-Snippet
        gen_docs_raw = kontext.get('generierte_dokumente', [])
        if gen_docs_raw:
            gen_docs_lines = []
            for gd in gen_docs_raw:
                raw_snippet = gd.get('inhalt_snippet') or ''
                snippet = str(raw_snippet).strip()
                kurz = snippet[0:400]  # type: ignore[index]
                zeile = f"  [{gd.get('typ', '–')}] {gd.get('betreff', '?')} ({gd.get('erstellt_am', 'k.A.')})"
                if kurz:
                    zeile += f"\n    Inhalt: {kurz}..."
                gen_docs_lines.append(zeile)
            gen_docs_text = "\n".join(gen_docs_lines)
        else:
            gen_docs_text = "Noch keine KI-generierten Briefe vorhanden."

        # Gegenstandswert aus Finanzdaten berechnen (Summe aller Soll-Beträge)
        gegenstandswert = sum(p.get('soll', 0) for p in finanzdaten_raw)

        # Stage-Detection: Falltyp erkennen + Workflow aus RAG laden
        falltyp = await self._erkenne_falltyp(kontext, ki_memory)
        workflow_kontext = await self._lade_workflow_kontext(falltyp)

        # IBAN-Status für Loki (Fakt aus DB, kein Raten)
        iban_hinterlegt = bool(kontext.get('mandant_bankverbindung', '').strip())

        from datetime import datetime as _dt
        heute_str = _dt.now().strftime("%d.%m.%Y")

        # RAG: ALLE Dokument-Inhalte dieser Akte laden — vollständig, wie Anwalt der Akte liest
        akte_rag_text = ""
        try:
            from app.services.rag_store import rag_store  # type: ignore[attr-defined]
            alle_chunks = rag_store.get_alle_akte_chunks(akte_id)
            if alle_chunks:
                chunk_parts = []
                aktueller_titel = None
                for chunk in alle_chunks:
                    meta = chunk.get("metadata", {})
                    titel_c = meta.get("titel", "?")
                    kat_c = meta.get("kategorie", "?")
                    if titel_c != aktueller_titel:
                        chunk_parts.append(f"\n[{kat_c}: {titel_c}]")
                        aktueller_titel = titel_c
                    chunk_parts.append(str(chunk.get("text", "")))  # type: ignore[arg-type]
                akte_rag_text = "\n".join(chunk_parts).strip()
                logger.info(f"handle_akte_chat: {len(alle_chunks)} Chunks (vollständig) für Akte {akte_id} geladen.")
        except Exception as _rag_err:
            logger.warning(f"akte_dokumente Vollladung fehlgeschlagen (akte_id={akte_id}): {_rag_err}")

        system_prompt = f"""Du bist Loki, der KI-Assistent der Kanzlei AWR24. Du hast VOLLSTÄNDIGEN Zugriff auf folgende Akte:

HEUTIGES DATUM: {heute_str} — nutze dieses Datum als Basis für alle Fristen und Aufgaben!
AKTE-ID (für Tool-Aufrufe): {akte_id}
AKTENZEICHEN: {kontext.get('aktenzeichen', '')}
MANDANT: {kontext.get('mandant', '')}
GEGNER/VERSICHERUNG: {kontext.get('gegner', '')}
ZIEL/MANDAT: {kontext.get('ziel', 'Nicht angegeben')}
STATUS: {kontext.get('status', '')}
GEGENSTANDSWERT (Summe Soll-Beträge Finanzen): {gegenstandswert:.2f} €

FINANZDATEN (bereits vollständig geladen):
{finanzdaten_text}

DOKUMENTE IN DER AKTE (hochgeladene Dateien, Scans — Metadaten):
{dokumente_text}

KANZLEI-ABKÜRZUNGEN (in Dokumenttiteln und Texten — verbindlich für die gesamte Akte):
Mdt. / MDT  = Mandant          |  Vers. / VERS  = Versicherung / Gegner
SV          = Sachverständiger  |  GA            = Gutachten
VM          = Vollmacht         |  VN            = Versicherungsnehmer
VU          = Verkehrsunfall    |  STA           = Staatsanwaltschaft / Staatsanwalt
ZM          = Zahlungsmitteilung / Zahlungsaufforderung
GDV         = Gesamtverband der Deutschen Versicherungswirtschaft (Branchenverband)
DS          = Deckungsschutz    |  RG            = Regulierung
RW          = Restwert          |  AN            = Anforderung
KZ          = Kennzeichen       |  AZ            = Aktenzeichen
REP         = Reparatur         |  NU            = Nutzungsausfall
AWR24       = Kanzlei (RA Winter, Aktenzeichen-Präfix)
Erstanschr. = Erstanschreiben   |  Bestät.       = Bestätigung

DOKUMENT-INHALTE (VOLLSTÄNDIGER Akteninhalt — alle indexierten Dokumente dieser Akte):
{akte_rag_text if akte_rag_text else "Keine indizierten Dokument-Inhalte (Dokumente noch nicht im Suchindex — ggf. index_alle_dokumente ausführen)."}

GENERIERTE BRIEFE (durch Loki erstellte Schreiben — Inhalt vollständig lesbar):
{gen_docs_text}

OFFENE AUFGABEN:
{aufgaben_text}

FRISTEN:
{fristen_text}

FRAGEBOGEN-DATEN:
{kontext.get('fragebogen', {})}

KI-MEMORY (Fakten aus früheren Sessions — NUR lesen, nie erfinden):
{ki_memory if ki_memory else "Noch keine Einträge."}

ERKANNTER FALLTYP: {falltyp}

WORKFLOW-WISSEN FÜR DIESEN FALLTYP:
{workflow_kontext if workflow_kontext else "Kein spezifischer Workflow bekannt — allgemeine Unterstützung aktiv. Falls Falltyp unklar: User freundlich fragen welcher Rechtsbereich (Verkehrsunfall, Mietrecht, Arbeitsrecht etc.)."}

MANDANT IBAN/BANKVERBINDUNG IN DB: {"Ja, hinterlegt" if iban_hinterlegt else "NEIN — noch nicht eingetragen (wird für Auszahlungen benötigt)"}

AKTIVER TAB: {active_tab}
{_tab_hinweis(active_tab)}

WICHTIGE REGELN:
- ABSOLUTES MARKDOWN-VERBOT: Verwende in KEINER Antwort Markdown-Formatierung. Weder **Fettschrift**, noch *Kursivschrift*, noch ## Überschriften, noch - Aufzählungszeichen, noch 1. nummerierte Listen mit Sternchen oder Rauten. Schreibe ausschließlich in normalem Fließtext mit Absätzen. Wenn du Punkte aufzählen willst, schreibe sie als Satz oder mit Ziffern ohne Sternchen.
- Die AKTE-ID für alle Tool-Aufrufe ist: {akte_id} — verwende sie DIREKT, frage den User NIEMALS danach.
- KI-MEMORY nach jeder bestätigten Aktion mit `aktualisiere_ki_memory` aktualisieren.
- Nach Brief-Erstellung (`erstelle_brief`): Speichere SOFORT in ki_memory: Datum + Empfänger + Betreff + die ersten 400 Zeichen des Brieftextes. Beispiel: "[26.03.2026] Erstanschreiben Vers. (Betreff: Schadensregulierung): Hiermit zeigen wir an, dass wir Herrn Kalaycioglu in der obengenannten Angelegenheit mandatiert wurden..."
- Wenn Falltyp erkannt und NICHT im KI-MEMORY: beim ersten Chat-Aufruf EINMALIG speichern: aktualisiere_ki_memory mit "Falltyp: {falltyp}".
- Wenn User fragt "Was soll ich als nächstes tun?" oder ähnliches: Antwort aus WORKFLOW-WISSEN oben ableiten und aktuelle Stufe anhand Dokumente/Aufgaben/KI-MEMORY bestimmen.
- WORKFLOW-LÜCKEN EIGENANALYSE: Leite Lücken SELBST aus den DOKUMENT-INHALTEN und der Dokumentliste ab — nicht aus Titeln raten! Nutze dazu die KANZLEI-ABKÜRZUNGEN. Beispiel: Gibt es ein Schreiben an Vers. aber keines an Mdt.? Wurde nach IBAN gefragt? Liegt eine Vollmacht vor? Weise den User aktiv auf echte Lücken hin — aber nur wenn du sie durch Inhaltslesen BELEGEN kannst.
- IBAN: Wenn "MANDANT IBAN" oben "NEIN" zeigt: weise aktiv darauf hin, dass die IBAN noch nicht in den Stammdaten hinterlegt ist.
- Du hast ALLE Finanzdaten, Dokumente und Aufgaben oben vollständig — nutze sie direkt aus dem Kontext.
- Frage NIEMALS nach Daten, die bereits im obigen Kontext stehen.
- GEGENSTANDSWERT für RVG = Summe der Soll-Beträge in den Finanzdaten (oben ausgewiesen). Wenn dieser Wert 0 oder sehr niedrig ist (z.B. nur Kostenpauschale), weise den User darauf hin, dass zuerst die Schadenspositionen (Reparatur, Gutachten etc.) eingetragen werden sollten, bevor RVG sinnvoll berechnet werden kann.
- Antworte immer auf Deutsch, präzise und kanzlei-professionell.

BRIEFE — ZWEISTUFIGER ABLAUF (PFLICHT, GILT FÜR JEDEN BRIEF EINZELN):
Schritt 1 — Entwurf zeigen:
  Wenn der User einen Brief anfordert (Erstanschreiben, Sachstandsinfo, Widerspruch etc.),
  schreibe den vollständigen Brieftext ZUERST als Entwurf direkt in den Chat.
  Nur Fließtext: kein Briefkopf, kein Datum, keine Anrede, kein "Mit freundlichen Grüßen".
  Kein Markdown (gilt generell, siehe oben).
  Beende die Antwort mit: "Soll ich diesen Brief so speichern? (Ja / Nein oder Änderungswunsch)"

Schritt 2 — Speichern nach Bestätigung:
  Rufe `erstelle_brief` NUR auf wenn der User explizit bestätigt ("Ja", "Speichern", "Ok" o.ä.).
  Falls der User Änderungen wünscht: überarbeite den Entwurf und zeige ihn erneut (→ wieder Schritt 1).
  NIEMALS `erstelle_brief` aufrufen ohne ausdrückliche Bestätigung des Users.
  NIEMALS mehrere Briefe gleichzeitig erstellen oder speichern — immer einen nach dem anderen.
  Beim Doppelpack (Versicherung + Mandant): erst Brief an Versicherung zeigen → User prüft/korrigiert → speichern → DANN Brief an Mandant zeigen → User prüft/korrigiert → speichern.

- Wenn der User einen Brief mit RVG-Gebühren anfordert:
  1. Prüfe ob die FINANZDATEN oben bereits RVG-Positionen enthalten.
  2. Falls KEINE RVG-Positionen vorhanden: Nutze zuerst `berechne_rvg`.
  3. Dann den Entwurf mit den Gebühren im Chat zeigen (Schritt 1).
- Die RVG-Gebühren werden AUTOMATISCH aus dem Gegenstandswert der Akte berechnet — frage NICHT danach.

ANDERE AKTIONEN (Aufgabe erstellen, Status ändern):
- AUFGABE ERSTELLEN: Rufe `erstelle_aufgabe` SOFORT auf wenn der User eine Aufgabe erstellen möchte — kein Bestätigungsschritt notwendig. Falls der User kein Datum nennt, frage zuerst "Bis wann?" und warte auf die Antwort, bevor du das Tool aufrufst.
- STATUS ÄNDERN: Kündige an und warte auf Bestätigung ("Ja", "Ok", "Mach das" etc.), bevor du `aendere_aktenstatus` aufrufst.
- WICHTIG: Rufe Tools TATSÄCHLICH auf — antworte NIEMALS nur mit Text "Aufgabe erstellt" oder "Status geändert" ohne den entsprechenden Tool-Aufruf durchzuführen!
"""

        tools = [
            {
                "function_declarations": [
                    {
                        "name": "get_finanzdaten",
                        "description": "Aktuelle Zahlungspositionen und Finanzdaten der Akte abrufen",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER", "description": "Die Akte-ID"}
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "erstelle_aufgabe",
                        "description": "Eine neue Aufgabe für die Akte erstellen",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "titel": {"type": "STRING", "description": "Titel der Aufgabe"},
                                "beschreibung": {"type": "STRING", "description": "Beschreibung (optional)"},
                                "prioritaet": {"type": "STRING", "enum": ["hoch", "mittel", "niedrig"]},
                                "faellig_am": {"type": "STRING", "description": "Fälligkeitsdatum ISO-Format YYYY-MM-DD — PFLICHT. Falls der User kein Datum nennt, frage erst danach bevor du das Tool aufrufst."}
                            },
                            "required": ["akte_id", "titel", "faellig_am"]
                        }
                    },
                    {
                        "name": "erstelle_frist",
                        "description": "Eine neue Frist (Deadline) für die Akte eintragen. Nutze dies IMMER, wenn der User explizit eine Frist, Deadline oder ähnliches setzen möchte.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "bezeichnung": {"type": "STRING", "description": "Bezeichnung der Frist, z.B. 'Widerspruchsfrist', 'Frist zur Stellungnahme'"},
                                "frist_datum": {"type": "STRING", "description": "Datum der Frist im ISO-Format YYYY-MM-DD — PFLICHT. Falls der User kein Datum nennt, frage erst danach bevor du das Tool aufrufst."},
                                "prioritaet": {"type": "STRING", "enum": ["hoch", "mittel", "niedrig"]}
                            },
                            "required": ["akte_id", "bezeichnung", "frist_datum"]
                        }
                    },
                    {
                        "name": "aendere_aktenstatus",
                        "description": "Den Status der Akte ändern (z.B. auf Geschlossen setzen)",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "neuer_status": {"type": "STRING", "enum": ["Offen", "Geschlossen", "Archiviert"]}
                            },
                            "required": ["akte_id", "neuer_status"]
                        }
                    },
                    {
                        "name": "berechne_rvg",
                        "description": "RVG-Gebühren für die Akte automatisch berechnen und als Zahlungspositionen speichern. Nutze dies wenn der User einen Brief mit RVG-Gebühren anfordert und die Finanzdaten noch keine RVG-Positionen enthalten.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER", "description": "Die Akte-ID"}
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "erstelle_brief",
                        "description": "Einen professionellen Brief für die Akte erstellen und als Dokument speichern. Du schreibst den vollständigen Brieftext selbst (nur Fließtext, kein Briefkopf, keine Anrede, kein 'Mit freundlichen Grüßen'). Briefkopf, Datum, Anrede und Signatur werden automatisch ergänzt.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "empfaenger": {"type": "STRING", "enum": ["versicherung", "mandant"], "description": "'versicherung' = an Gegner/Versicherung adressiert; 'mandant' = an Mandant adressiert"},
                                "betreff": {"type": "STRING", "description": "Betreffzeile des Briefes. NUR das Thema, z.B. 'Schadensregulierung – Unfall vom 10.03.2026' oder 'Sachstandsinformation'. KEIN 'Unser Zeichen' und KEIN Aktenzeichen — das wird vom Template automatisch als eigenes Feld eingefügt."},
                                "brief_text": {"type": "STRING", "description": "Nur der Fließtext des Briefinhalts. KEIN Briefkopf, KEIN Datum, KEINE Anrede ('Sehr geehrte...'), KEIN Schluss ('Mit freundlichen Grüßen'). Diese Teile werden automatisch aus der Vorlage ergänzt."}
                            },
                            "required": ["akte_id", "empfaenger", "betreff", "brief_text"]
                        }
                    },
                    {
                        "name": "aktualisiere_ki_memory",
                        "description": "KI-Memory der Akte mit einem neuen Fakteneintrag aktualisieren. "
                                       "NUR nach erfolgreich ausgeführter Aktion aufrufen (nicht spekulativ). "
                                       "Beispiel: 'Erstanschreiben Vers. erstellt 24.03.2026'",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "eintrag": {"type": "STRING", "description": "Faktischer Eintrag, max. 1-2 Sätze"}
                            },
                            "required": ["akte_id", "eintrag"]
                        }
                    },
                    {
                        "name": "erstelle_zahlungspositionen",
                        "description": "Zahlungspositionen (Forderungen) in den Finanzen der Akte anlegen. Nutze dies wenn der User Beträge eintragen möchte, z.B. Gutachten, Kostenpauschale, Reparaturkosten, Sachverständigengebühren.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "positionen": {
                                    "type": "ARRAY",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "beschreibung": {"type": "STRING", "description": "Bezeichnung der Position, z.B. 'Kostenpauschale', 'Schadensgutachten (netto)'"},
                                            "soll_betrag": {"type": "NUMBER", "description": "Betrag in Euro (Forderung)"},
                                            "category": {"type": "STRING", "description": "Kategorie: Gutachten | SV-Kosten | Reparatur | Mietfahrzeug | Schmerzensgeld | Kostenpauschale | RVG | Sonstiges"}
                                        },
                                        "required": ["beschreibung", "soll_betrag", "category"]
                                    },
                                    "description": "Liste der anzulegenden Zahlungspositionen"
                                }
                            },
                            "required": ["akte_id", "positionen"]
                        }
                    },
                    {
                        "name": "buche_zahlung",
                        "description": (
                            "Zahlungseingang (Haben-Betrag) gegen eine bestehende Zahlungsposition buchen. "
                            "Nutze dies wenn die Versicherung gezahlt hat und der Betrag im Finanz-Tab eingetragen werden soll. "
                            "Die zahlungsposition_id findest du in den FINANZDATEN des Kontexts (Feld 'id'). "
                            "Status wird automatisch gesetzt: BEZAHLT wenn haben >= soll, sonst TEILBEZAHLT."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "zahlungsposition_id": {"type": "INTEGER", "description": "ID der Zahlungsposition aus den FINANZDATEN (Feld 'id')"},
                                "haben_betrag": {"type": "NUMBER", "description": "Eingegangener Betrag in Euro"},
                            },
                            "required": ["zahlungsposition_id", "haben_betrag"]
                        }
                    }
                ]
            }
        ]

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # Vertex AI erfordert mindestens einen Content — bei leeren messages (Analyse-Start) Dummy einfügen
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Analysiere diese Akte und gib mir eine strukturierte Übersicht mit Handlungsempfehlungen."}]}]

        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            tools=tools,
            system_instruction=system_prompt,
            thinking_config=genai_types.ThinkingConfig(include_thoughts=False),
        )

        # Gemini aufrufen mit Function Calling
        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                return {
                    "reply": "⏳ Gemini API Tageslimit erreicht. Bitte in einigen Minuten erneut versuchen.",
                    "actions_taken": []
                }
            raise

        actions_taken = []
        while response.candidates and response.candidates[0].content.parts and getattr(response.candidates[0].content.parts[0], 'function_call', None):
            fc = response.candidates[0].content.parts[0].function_call
            try:
                fc_args_dict = {k: v for k, v in fc.args.items()}
            except Exception:
                fc_args_dict = dict(fc.args)

            tool_result = await self._execute_chat_tool(fc.name, fc_args_dict)
            actions_taken.append({"tool": fc.name, "result": tool_result})

            # Tool-Ergebnis zurück an Gemini
            contents.append(response.candidates[0].content)
            contents.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part(function_response=genai_types.FunctionResponse(
                    name=fc.name,
                    response={"result": tool_result}
                ))]
            ))
            try:
                response = await gemini.client.aio.models.generate_content(
                    model=gemini.model_name,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                    return {
                        "reply": "⏳ Gemini API Tageslimit erreicht. Bitte in einigen Minuten erneut versuchen.",
                        "actions_taken": actions_taken
                    }
                raise

        try:
            reply_text = response.text if response.candidates else "Keine Antwort von KI."
        except ValueError:
            # Gemini hat keine Text-Antwort (z.B. nur unaufgelöste Function Calls)
            reply_text = "Die Anfrage konnte nicht verarbeitet werden. Bitte formuliere sie anders oder nutze eine der verfügbaren Aktionen."
        return {"reply": _strip_markdown(reply_text), "actions_taken": actions_taken}


# Singleton
query_service = QueryService()
