"""
VorlagenSuggestService — KI-Baustein-Empfehlung für Erstanschreiben

Aufgabe:
  - Analysiert fragebogen_data.schadenshergang mit Gemini
  - Bestimmt Unfalltyp (Auffahrunfall, Parkschaden, etc.)
  - Empfiehlt passende Bausteine aus der übergebenen Liste
  - Bedingte Blöcke werden DETERMINISTISCH aus Fragebogen-Feldern berechnet (kein LLM nötig)
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ===========================================================================
# DETERMINISTISCH: Bedingte Blöcke direkt aus Fragebogen-Feldern
# Kein LLM-Aufruf nötig — reine Python-Logik
# ===========================================================================
BEDINGTE_BLOECKE_REGELN = {
    "gutachten": {
        "bedingung": lambda fb: fb.get("sv_beauftragt") is True,
        "begruendung": "Sachverständiger wurde beauftragt (sv_beauftragt = true)",
    },
    "personenschaden": {
        "bedingung": lambda fb: fb.get("personenschaden") is True,
        "begruendung": "Personenschaden wurde angegeben (personenschaden = true)",
    },
    "bank": {
        "bedingung": lambda fb: fb.get("kfz_finanziert") is True,
        "begruendung": "Fahrzeug ist finanziert (kfz_finanziert = true)",
    },
    "leasing": {
        "bedingung": lambda fb: fb.get("kfz_geleast") is True,
        "begruendung": "Fahrzeug ist geleast (kfz_geleast = true)",
    },
    "mietwagen": {
        "bedingung": lambda fb: fb.get("mietwagen_nutzungsausfall") == "mietwagen",
        "begruendung": "Mietwagen wurde beantragt",
    },
}


def berechne_bedingte_bloecke(fragebogen_data: dict) -> list[dict]:
    """
    Berechnet bedingte Blöcke deterministisch aus fragebogen_data.
    Kein LLM-Aufruf — direkte Feldauswertung.
    """
    ergebnis = []
    for kategorie, regel in BEDINGTE_BLOECKE_REGELN.items():
        aktiv = False
        begruendung = f"{kategorie}: Bedingung nicht erfüllt"
        try:
            aktiv = regel["bedingung"](fragebogen_data)
            if aktiv:
                begruendung = regel["begruendung"]
        except Exception:
            pass

        ergebnis.append({
            "kategorie": kategorie,
            "aktiv": aktiv,
            "begruendung": begruendung,
        })

    return ergebnis


# ===========================================================================
# KI-GESTÜTZT: Unfalltyp-Erkennung und Baustein-Empfehlung via Gemini
# ===========================================================================

UNFALLTYP_MAPPING = {
    "auffahrunfall":    ["aufgefahren", "auffuhr", "auffährt", "aufgefahrenen", "stehende", "aufprall hinten"],
    "parkschaden":      ["geparkt", "parkend", "parkplatz", "abgestellt", "stand", "parkiert"],
    "spurwechsel":      ["spur gewechselt", "spurwechsel", "fahrstreifen", "eingeschert", "einscherte"],
    "vorfahrt":         ["vorfahrt", "vorfahrtsstraße", "stoppschild", "stop-schild", "hatte vorfahrt"],
    "einparken":        ["einparken", "einparkmanöver", "rückwärts gefahren", "rangiert"],
    "rotlicht":         ["rote ampel", "rotlicht", "bei rot", "ampel missachtet"],
}


def klassifiziere_unfalltyp_einfach(schadenshergang: str) -> tuple[str, float]:
    """
    Einfache keyword-basierte Klassifikation als Fallback (ohne LLM).
    Gibt (unfalltyp, confidence) zurück.
    """
    text_lower = schadenshergang.lower()
    treffer = {}

    for unfalltyp, keywords in UNFALLTYP_MAPPING.items():
        punkte = sum(1 for kw in keywords if kw in text_lower)
        if punkte > 0:
            treffer[unfalltyp] = punkte

    if not treffer:
        return "freitext", 0.5

    bester_typ = max(treffer, key=lambda k: treffer[k])
    # Confidence: 0.75 bei 1 Treffer, 0.90 bei 2+
    confidence = 0.90 if treffer[bester_typ] >= 2 else 0.75
    return bester_typ, confidence


async def klassifiziere_mit_gemini(
    gemini_client: Any,
    schadenshergang: str,
    verfuegbare_bausteine: list[dict],
) -> dict:
    """
    Klassifiziert Schadenshergang via Gemini und empfiehlt Bausteine.
    Gibt strukturiertes Ergebnis zurück.
    """
    # Bausteine für Unfallhergang zusammenstellen (für Kontext im Prompt)
    unfallhergang_bausteine = [
        b for b in verfuegbare_bausteine
        if b.get("kategorie") == "unfallhergang"
    ]
    bausteine_text = "\n".join([
        f"  ID={b['id']}: {b['titel']} | Tags: {b.get('tags', [])}"
        for b in unfallhergang_bausteine
    ])

    prompt = f"""Du bist Rechtsassistent einer Anwaltskanzlei für Verkehrsrecht (Deutschland).

AUFGABE:
Analysiere den Schadenshergang und wähle den passenden Unfallhergang-Baustein.

SCHADENSHERGANG:
"{schadenshergang}"

VERFÜGBARE BAUSTEINE (Kategorie: unfallhergang):
{bausteine_text if bausteine_text else "Keine Bausteine verfügbar"}

ANTWORTFORMAT (NUR dieses JSON, KEIN Text davor oder danach):
{{
  "unfalltyp": "auffahrunfall|parkschaden|spurwechsel|vorfahrt|einparken|rotlicht|freitext",
  "empfohlener_baustein_id": <Ganzzahl-ID aus der Liste ODER null wenn freitext>,
  "confidence": <Zahl zwischen 0.0 und 1.0>,
  "begruendung": "<1-2 Sätze warum dieser Baustein passt>"
}}"""

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        # Synchroner Aufruf in Thread-Pool um FastAPI nicht zu blockieren
        raw = await loop.run_in_executor(
            None,
            lambda: gemini_client.generate(prompt)
        )
        raw = raw.strip()

        # JSON aus Antwort extrahieren (falls Gemini Text davor/danach hat)
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start >= 0 and end > start:
            raw_json = raw[start:end]
            result = json.loads(raw_json)
            logger.info(f"Gemini Klassifikation: {result.get('unfalltyp')} ({result.get('confidence')})")
            return result
        else:
            raise ValueError(f"Kein JSON in Gemini-Antwort: {raw[:200]}")

    except Exception as e:
        logger.warning(f"Gemini-Klassifikation fehlgeschlagen, nutze Keyword-Fallback: {e}")
        unfalltyp, confidence = klassifiziere_unfalltyp_einfach(schadenshergang)

        # Passenden Baustein nach Tag suchen
        empfohlener_id = None
        for b in unfallhergang_bausteine:
            tags = [t.lower() for t in b.get("tags", [])]
            if f"#{unfalltyp}" in tags or unfalltyp in tags:
                empfohlener_id = b["id"]
                break

        return {
            "unfalltyp": unfalltyp,
            "empfohlener_baustein_id": empfohlener_id,
            "confidence": confidence,
            "begruendung": f"Keyword-Analyse (Gemini nicht verfügbar): {unfalltyp} erkannt",
        }


async def erstelle_suggest_antwort(
    fragebogen_data: dict,
    vorlage_typ: str,
    verfuegbare_bausteine: list[dict],
    gemini_client: Any = None,
) -> dict:
    """
    Hauptfunktion: Erstellt vollständige Suggest-Antwort.

    1. Bedingte Blöcke: deterministisch
    2. Unfalltyp + Baustein-Empfehlung: Gemini oder Keyword-Fallback
    3. Hinweise-Bausteine: nach Tags aus verfuegbaren_bausteine

    Returns:
        {
            "vorgeschlagene_bausteine": {...},
            "bedingte_bloecke": [...],
            "unfalltyp_erkannt": "...",
            "confidence_gesamt": 0.0-1.0,
            "fallback_modus": bool
        }
    """
    schadenshergang = fragebogen_data.get("schadenshergang", "").strip()

    # --- 1. Bedingte Blöcke (deterministisch, kein LLM) ---
    bedingte_bloecke = berechne_bedingte_bloecke(fragebogen_data)

    # --- 2. Unfalltyp-Klassifikation ---
    fallback_modus = False
    if schadenshergang and gemini_client:
        ki_ergebnis = await klassifiziere_mit_gemini(
            gemini_client, schadenshergang, verfuegbare_bausteine
        )
    elif schadenshergang:
        unfalltyp, confidence = klassifiziere_unfalltyp_einfach(schadenshergang)
        ki_ergebnis = {
            "unfalltyp": unfalltyp,
            "empfohlener_baustein_id": None,
            "confidence": confidence,
            "begruendung": "Keyword-Analyse (kein KI-Modell konfiguriert)",
        }
        fallback_modus = True
    else:
        ki_ergebnis = {
            "unfalltyp": "unbekannt",
            "empfohlener_baustein_id": None,
            "confidence": 0.0,
            "begruendung": "Kein Schadenshergang vorhanden — manuelle Auswahl erforderlich",
        }
        fallback_modus = True

    # --- 3. Standard-Hinweise-Bausteine ---
    # Immer: Reparaturfreigabe + Haftung 100%
    hinweise_bausteine = [
        b for b in verfuegbare_bausteine
        if b.get("kategorie") == "hinweise_versicherung"
        and any(t in ["#reparaturfreigabe", "#haftung100", "#standard"] for t in b.get("tags", []))
    ]

    # Wenn keine Tags gesetzt: erste 2 hinweise_versicherung nehmen
    if not hinweise_bausteine:
        hinweise_bausteine = [
            b for b in verfuegbare_bausteine
            if b.get("kategorie") == "hinweise_versicherung"
        ][:2]

    return {
        "vorgeschlagene_bausteine": {
            "unfallhergang": {
                "baustein_id": ki_ergebnis.get("empfohlener_baustein_id"),
                "confidence": ki_ergebnis.get("confidence", 0.0),
                "begruendung": ki_ergebnis.get("begruendung", ""),
            },
            "hinweise": [
                {
                    "baustein_id": b["id"],
                    "confidence": 0.85,
                    "begruendung": f"Standard-Hinweis: {b['titel']}",
                }
                for b in hinweise_bausteine
            ],
        },
        "bedingte_bloecke": bedingte_bloecke,
        "unfalltyp_erkannt": ki_ergebnis.get("unfalltyp", "unbekannt"),
        "confidence_gesamt": ki_ergebnis.get("confidence", 0.0),
        "fallback_modus": fallback_modus,
    }
