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
            f"gemini-2.0-flash:generateContent?key={self.gemini_api_key}"
        )
        self.django_base = settings.backend_url.rstrip("/")
        self.django_headers = {
            "Authorization": f"Bearer {settings.backend_api_token}",
            "Content-Type": "application/json",
        }

    async def handle_query(self, query: str, user_id: int) -> Dict[str, Any]:
        """
        Haupteinstiegspunkt: Freitext → Gemini → Tool-Call → Django → formatiertes Ergebnis.
        """
        if not self.gemini_api_key:
            return {"status": "error", "error": "Gemini API Key nicht konfiguriert."}

        logger.info(f"QueryService: Verarbeite Anfrage von User {user_id}: '{query[:80]}'")

        # 1. Gemini Function Calling → Tool + Parameter bestimmen
        function_call = await self._classify_with_gemini(query)

        if not function_call:
            return {
                "status": "ok",
                "result_type": "text",
                "data": (
                    "Ich konnte die Anfrage leider keinem meiner Werkzeuge zuordnen. "
                    "Versuche es mit einer spezifischeren Frage, z.B. "
                    "\"Zeig mir alle offenen Akten\" oder \"Wieviele Fälle gibt es dieses Jahr?\"."
                ),
                "query_used": None,
            }

        tool_name = function_call.get("name")
        tool_args = function_call.get("args", {})
        logger.info(f"Gemini wählte Tool: {tool_name}, Args: {tool_args}")

        # 2. Django-Endpoint aufrufen
        raw_data = await self._execute_tool(tool_name, tool_args)

        if raw_data is None:
            return {
                "status": "error",
                "error": f"Datenbankabfrage für '{tool_name}' fehlgeschlagen.",
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

    # -----------------------------------------------------------------------
    # Tool-Dispatch → Django /api/ai/query/* Endpoints
    # -----------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Optional[Any]:
        """Routet den Tool-Call zum passenden Django-Endpoint."""
        tool_map = {
            "get_akten_liste": self._get_akten_liste,
            "get_offene_betraege": self._get_offene_betraege,
            "count_faelle": self._count_faelle,
            "get_akten_ohne_fragebogen": self._get_akten_ohne_fragebogen,
            "get_fristen_naechste_tage": self._get_fristen_naechste_tage,
            "get_akte_by_aktenzeichen": self._get_akte_by_aktenzeichen,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            logger.warning(f"Unbekanntes Tool: {tool_name}")
            return None

        try:
            return await handler(**args)
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

        if tool_name in ("get_akten_liste", "get_akten_ohne_fragebogen"):
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


# Singleton
query_service = QueryService()
