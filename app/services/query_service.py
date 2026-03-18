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
# QUERY SERVICE
# ===========================================================================

class QueryService:
    """
    Verarbeitet Freitext-Anfragen via Gemini Function Calling
    und ruft die entsprechenden Django /api/ai/query/* Endpoints auf.
    """

    def __init__(self):
        self.gemini_api_key = settings.gemini_api_key
        self.gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        self.django_base = settings.backend_url.rstrip("/")
        self.django_headers = {
            "Authorization": f"Bearer {settings.backend_api_token}",
            "Content-Type": "application/json",
        }

    async def handle_query(self, query: str, user_id: int, akte_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Haupteinstiegspunkt: Freitext → Gemini → Tool-Call → Django → formatiertes Ergebnis.
        """
        if not self.gemini_api_key:
            return {"status": "error", "error": "Gemini API Key nicht konfiguriert."}

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
        Sendet die Anfrage an Gemini mit Function Calling.
        Gibt den gewählten Tool-Call zurück oder None wenn kein Tool passt.
        """
        system_text = (
            "Du bist eine KI-Sekretärin für eine Kanzlei (Verkehrsrecht). "
            "Analysiere die Anfrage und wähle das passende Werkzeug aus. "
            "Wähle genau ein Werkzeug. Wenn keine Anfrage zu den Werkzeugen passt, "
            "antworte ohne Werkzeug-Aufruf."
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_text}\n\nAnfrage: {query}"}],
                }
            ],
            "tools": [{"function_declarations": TOOL_DECLARATIONS}],
            "tool_config": {
                "function_calling_config": {"mode": "AUTO"}
            },
            "generationConfig": {
                "temperature": 0.0,  # Deterministisch für Tool-Auswahl
            },
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(self.gemini_url, json=payload)
                response.raise_for_status()
                data = response.json()

            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("Gemini lieferte keine Candidates zurück.")
                return None

            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "functionCall" in part:
                    return part["functionCall"]

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
        
        # 3. Gemini Response generieren
        system_prompt = (
            "Du bist ein hilfreicher Assistent für das Kanzlei-Programm. "
            "Beantworte die Frage des Nutzers AUSSCHLIESSLICH basierend auf dem folgenden System-Wissen. "
            "Erfinde keine Funktionen hinzu. Halte dich kurz und prägnant."
        )
        
        prompt = f"{system_prompt}\n\nSYSTEM-WISSEN:\n{context_str}\n\nFRAGE DES NUTZERS:\n{query}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2}
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.gemini_url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                    answer_text = candidates[0]["content"]["parts"][0].get("text", "")
                    return {
                        "status": "ok",
                        "result_type": "text",
                        "data": answer_text,
                        "query_used": "rag_system_wissen",
                    }
                else:
                    return {
                        "status": "error",
                        "error": "Konnte keine Antwort aus dem System-Wissen generieren."
                    }
        except Exception as e:
            logger.error(f"Fehler bei der Fallback-Antwort Generierung: {e}")
            return {
                "status": "error",
                "error": "Fehler bei der Formulierung der System-Antwort."
            }

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
            "WICHTIG: Generiere NUR den Brieftext ab der Anrede ('Sehr geehrte...') bis zur Grußformel.\n"
            "KEIN Briefkopf, KEINE Adresse, KEIN Datum, KEIN Aktenzeichen am Anfang.\n"
            "Der Briefkopf wird vom System automatisch eingefügt.\n"
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

        async with httpx.AsyncClient(timeout=15.0) as client:
            if tool_name == "get_finanzdaten":
                resp = await client.get(
                    f"{self.django_base}/api/ai/query/finanzdaten/",
                    params={"akte_id": args["akte_id"]},
                    headers=headers
                )
                return resp.json()

            elif tool_name == "erstelle_aufgabe":
                resp = await client.post(
                    f"{self.django_base}/api/ai/actions/erstelle_aufgabe/",
                    json=args, headers=headers
                )
                return resp.json()

            elif tool_name == "aendere_aktenstatus":
                resp = await client.post(
                    f"{self.django_base}/api/ai/actions/aendere_aktenstatus/",
                    json=args, headers=headers
                )
                return resp.json()

            elif tool_name == "berechne_rvg":
                resp = await client.post(
                    f"{self.django_base}/api/ai/actions/berechne_rvg/",
                    json=args, headers=headers
                )
                return resp.json()

            elif tool_name == "erstelle_brief":
                # Brief speichern — Gemini hat den Text bereits im Tool-Call generiert
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
                return resp.json()

        return {"error": f"Unbekanntes Tool: {tool_name}"}

    async def handle_akte_chat(
        self,
        akte_id: int,
        messages: list[dict],
        kontext: dict,
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
                cat = p.get('category', '–')
                beschr = p.get('beschreibung', '–')
                soll = p.get('soll', 0)
                haben = p.get('haben', 0)
                st = p.get('status', '–')
                fd_lines.append(f"  [{cat}] {beschr}: Forderung={soll:.2f}€, Erhalten={haben:.2f}€, Status={st}")
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

        system_prompt = f"""Du bist Loki, der KI-Assistent der Kanzlei AWR24. Du hast VOLLSTÄNDIGEN Zugriff auf folgende Akte:

AKTE-ID (für Tool-Aufrufe): {akte_id}
AKTENZEICHEN: {kontext.get('aktenzeichen', '')}
MANDANT: {kontext.get('mandant', '')}
GEGNER/VERSICHERUNG: {kontext.get('gegner', '')}
ZIEL/MANDAT: {kontext.get('ziel', 'Nicht angegeben')}
STATUS: {kontext.get('status', '')}

FINANZDATEN (bereits vollständig geladen):
{finanzdaten_text}

OFFENE AUFGABEN:
{aufgaben_text}

FRISTEN:
{fristen_text}

FRAGEBOGEN-DATEN:
{kontext.get('fragebogen', {})}

WICHTIGE REGELN:
- Die AKTE-ID für alle Tool-Aufrufe ist: {akte_id} — verwende sie DIREKT, frage den User NIEMALS danach.
- Du hast ALLE Finanzdaten und Aufgaben oben vollständig — nutze sie direkt aus dem Kontext.
- Frage NIEMALS nach Daten, die bereits im obigen Kontext stehen.
- Antworte immer auf Deutsch, präzise und kanzlei-professionell.

BRIEFE — ZWEISTUFIGER ABLAUF (PFLICHT):
Schritt 1 — Entwurf zeigen:
  Wenn der User einen Brief anfordert (Erstanschreiben, Sachstandsinfo, Widerspruch etc.),
  schreibe den vollständigen Brieftext ZUERST als Entwurf direkt in den Chat.
  Nur Fließtext: kein Briefkopf, kein Datum, keine Anrede, kein "Mit freundlichen Grüßen".
  Beende die Antwort mit: "Soll ich diesen Brief so speichern? (Ja / Nein oder Änderungswunsch)"

Schritt 2 — Speichern nach Bestätigung:
  Rufe `erstelle_brief` NUR auf wenn der User explizit bestätigt ("Ja", "Speichern", "Ok" o.ä.).
  Falls der User Änderungen wünscht: überarbeite den Entwurf und zeige ihn erneut (→ wieder Schritt 1).
  NIEMALS `erstelle_brief` aufrufen ohne ausdrückliche Bestätigung des Users.

- Wenn der User einen Brief mit RVG-Gebühren anfordert:
  1. Prüfe ob die FINANZDATEN oben bereits RVG-Positionen enthalten.
  2. Falls KEINE RVG-Positionen vorhanden: Nutze zuerst `berechne_rvg`.
  3. Dann den Entwurf mit den Gebühren im Chat zeigen (Schritt 1).
- Die RVG-Gebühren werden AUTOMATISCH aus dem Gegenstandswert der Akte berechnet — frage NICHT danach.

ANDERE AKTIONEN (Aufgabe erstellen, Status ändern):
- Kündige diese im Chat an und warte auf Bestätigung ("Ja", "Ok", "Mach das" etc.).
"""

        import google.ai.generativelanguage as gl
        
        tools = [
            {
                "function_declarations": [
                    {
                        "name": "get_finanzdaten",
                        "description": "Aktuelle Zahlungspositionen und Finanzdaten der Akte abrufen",
                        "parameters": {
                            "type": gl.Type.OBJECT,
                            "properties": {
                                "akte_id": {"type": gl.Type.INTEGER, "description": "Die Akte-ID"}
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "erstelle_aufgabe",
                        "description": "Eine neue Aufgabe für die Akte erstellen",
                        "parameters": {
                            "type": gl.Type.OBJECT,
                            "properties": {
                                "akte_id": {"type": gl.Type.INTEGER},
                                "titel": {"type": gl.Type.STRING, "description": "Titel der Aufgabe"},
                                "beschreibung": {"type": gl.Type.STRING, "description": "Beschreibung (optional)"},
                                "prioritaet": {"type": gl.Type.STRING, "enum": ["hoch", "mittel", "niedrig"]},
                                "faellig_am": {"type": gl.Type.STRING, "description": "Fälligkeitsdatum ISO-Format YYYY-MM-DD (optional)"}
                            },
                            "required": ["akte_id", "titel"]
                        }
                    },
                    {
                        "name": "aendere_aktenstatus",
                        "description": "Den Status der Akte ändern (z.B. auf Geschlossen setzen)",
                        "parameters": {
                            "type": gl.Type.OBJECT,
                            "properties": {
                                "akte_id": {"type": gl.Type.INTEGER},
                                "neuer_status": {"type": gl.Type.STRING, "enum": ["Offen", "Geschlossen", "Archiviert"]}
                            },
                            "required": ["akte_id", "neuer_status"]
                        }
                    },
                    {
                        "name": "berechne_rvg",
                        "description": "RVG-Gebühren für die Akte automatisch berechnen und als Zahlungspositionen speichern. Nutze dies wenn der User einen Brief mit RVG-Gebühren anfordert und die Finanzdaten noch keine RVG-Positionen enthalten.",
                        "parameters": {
                            "type": gl.Type.OBJECT,
                            "properties": {
                                "akte_id": {"type": gl.Type.INTEGER, "description": "Die Akte-ID"}
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "erstelle_brief",
                        "description": "Einen professionellen Brief für die Akte erstellen und als Dokument speichern. Du schreibst den vollständigen Brieftext selbst (nur Fließtext, kein Briefkopf, keine Anrede, kein 'Mit freundlichen Grüßen'). Briefkopf, Datum, Anrede und Signatur werden automatisch ergänzt.",
                        "parameters": {
                            "type": gl.Type.OBJECT,
                            "properties": {
                                "akte_id": {"type": gl.Type.INTEGER},
                                "empfaenger": {"type": gl.Type.STRING, "enum": ["versicherung", "mandant"], "description": "'versicherung' = an Gegner/Versicherung adressiert; 'mandant' = an Mandant adressiert"},
                                "betreff": {"type": gl.Type.STRING, "description": "Betreffzeile des Briefes (z.B. 'Schadensregulierung – Ihr Zeichen: ...')"},
                                "brief_text": {"type": gl.Type.STRING, "description": "Nur der Fließtext des Briefinhalts. KEIN Briefkopf, KEIN Datum, KEINE Anrede ('Sehr geehrte...'), KEIN Schluss ('Mit freundlichen Grüßen'). Diese Teile werden automatisch aus der Vorlage ergänzt."}
                            },
                            "required": ["akte_id", "empfaenger", "betreff", "brief_text"]
                        }
                    }
                ]
            }
        ]

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        import google.generativeai as genai
        from app.config import settings
        
        chat_model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            tools=tools,
        )
        
        # System instruction als Teil der Conversation anhängen
        contents.insert(0, {"role": "user", "parts": [{"text": "SYSTEM INSTRUCTION: " + system_prompt}]})
        contents.insert(1, {"role": "model", "parts": [{"text": "Verstanden, ich werde diese Anweisungen befolgen."}]}) 

        # Gemini aufrufen mit Function Calling
        try:
            response = await chat_model.generate_content_async(contents)
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

            # Tool-Ergebnis zurück an Gemini (glm.Part erforderlich, Raw-Dict wird nicht akzeptiert)
            import google.ai.generativelanguage as gl
            contents.append(response.candidates[0].content)
            contents.append(gl.Content(
                role="user",
                parts=[gl.Part(function_response=gl.FunctionResponse(
                    name=fc.name,
                    response={"result": tool_result}
                ))]
            ))
            try:
                response = await chat_model.generate_content_async(contents)
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                    return {
                        "reply": "⏳ Gemini API Tageslimit erreicht. Bitte in einigen Minuten erneut versuchen.",
                        "actions_taken": actions_taken
                    }
                raise

        reply_text = response.text if response.candidates else "Keine Antwort von KI."
        return {"reply": reply_text, "actions_taken": actions_taken}


# Singleton
query_service = QueryService()
