# Kanzlei AI Service

KI-gestützter Service für die automatisierte Aktenanlage und Dokumentenverarbeitung.

## Übersicht

Dieser Service läuft **separat** von der Haupt-Anwendung und kommuniziert ausschließlich über REST API.

**Entwicklung:** Google Gemini API  
**Produktion:** Lokales LLM (Loki)

## Architektur

```
Frontend → Django Backend → AI Service → Gemini API / Loki
                ↓
           PostgreSQL
```

**Wichtig:** AI Service hat **KEINEN** direkten Datenbankzugriff!  
Alle Daten werden über Django REST API ausgetauscht.

## Features

- ✅ E-Mail + Anhänge analysieren
- ✅ Automatische Aktenanlage
- ✅ Stammdaten-Extraktion
- ✅ Dokumenten-Klassifizierung
- ✅ Ticket-Erstellung für Review

## Installation

### Voraussetzungen

- Python 3.11+
- Google Gemini API Key (Entwicklung)

### Setup

```bash
# Virtual Environment erstellen
python -m venv venv
venv\Scripts\activate  # Windows

# Dependencies installieren
pip install -r requirements.txt

# Environment-Variablen setzen
cp .env.example .env
# .env bearbeiten: GEMINI_API_KEY, BACKEND_URL, etc.
```

### Starten

```bash
# Entwicklung
uvicorn app.main:app --reload --port 5000

# Produktion
uvicorn app.main:app --host 0.0.0.0 --port 5000
```

## API Endpoints

### Health Check
```
GET /health
```

### Neue Akte erstellen
```
POST /api/akte/create-from-email
Content-Type: multipart/form-data

{
  "email_file": <file>,
  "attachments": [<files>]
}
```

## Konfiguration

Siehe `.env.example` für alle verfügbaren Umgebungsvariablen.

## Entwicklung

### Projekt-Struktur

```
app/
├── main.py              # FastAPI App
├── config.py            # Konfiguration
├── services/
│   ├── gemini_client.py # Gemini API Integration
│   ├── loki_client.py   # Lokales LLM (später)
│   ├── email_parser.py  # E-Mail Parsing
│   └── akte_creator.py  # Akten-Logik
└── models/
    └── schemas.py       # Pydantic Models
```

## Integration mit Haupt-App

Dieser Service ist als **Git Submodule** in `Kanzlei_V2_final` eingebunden:

```bash
cd Kanzlei_V2_final
git submodule add https://github.com/vadymkalchenko-sudo/Kanzlei_AI_Service.git ai-service
```

## Deployment

**Entwicklung:** Läuft auf Dev-Server neben Django  
**Produktion:** Läuft auf Loki-Rechner (WakeOnLAN bei Bedarf)

Siehe `DEPLOYMENT.md` für Details.

## Lizenz

Proprietär - Nur für interne Nutzung.
