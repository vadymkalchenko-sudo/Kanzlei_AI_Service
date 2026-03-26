# Kanzlei AI Service

KI-Backend für das Kanzlei V3 System (FastAPI, ChromaDB RAG, Gemini/Vertex AI).

## Übersicht

Läuft **separat** von der Hauptanwendung. Kommuniziert ausschließlich über REST API.
Kein direkter Datenbankzugriff — alle Daten über Django REST API.

```
Frontend → Django Backend (8001) → AI Service (5000) → Vertex AI / Gemini API / Loki
```

**Entwicklung:** `LLM_PROVIDER=gemini` (API-Key)
**Produktion:** `LLM_PROVIDER=vertex` (Service Account, europe-west3/Frankfurt, DSGVO-konform)

## Features

- ✅ E-Mail + Anhänge KI-Extraktion → automatische Aktenanlage
- ✅ RAG (ChromaDB) — `system_wissen`, `kanzlei_wissen`, `akte_dokumente`
- ✅ Loki Chat (Akte-Chat, Freitext, MCP-Sekretärin mit Tools)
- ✅ Falltyp-Erkennung + Workflow-Engine (aktenübergreifendes Grundwissen)
- ✅ Brief-Generierung (Versicherungsschreiben + Mandantenschreiben)
- ✅ Vorlagen-Empfehlung via RAG
- ✅ Vertex AI (Prod) / Gemini API (Dev) — gleiche Codebase, nur `.env` unterscheidet

## Setup (Entwicklung)

```bash
# Virtual Environment
python -m venv venv
venv\Scripts\activate   # Windows

# Dependencies
pip install -r requirements.txt

# Environment
cp .env.example .env
# .env bearbeiten: GEMINI_API_KEY, BACKEND_URL, BACKEND_API_TOKEN
```

## Starten (lokal)

```bash
# Empfohlen: über Docker (wegen chroma-hnswlib DLL auf Windows)
cd c:/Entwicklung/Kanzlei_AI_Service
docker compose up -d

# Alternativ direkt (wenn ChromaDB läuft):
uvicorn app.main:app --reload --port 5000
```

## Wichtige API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/health` | Service-Status + Provider-Info |
| POST | `/extract` | E-Mail/Dokument KI-Extraktion |
| POST | `/rag/feed` | Dokument in RAG einspeisen |
| GET | `/rag/stats` | RAG Füllstand (alle Collections) |
| POST | `/suggest/vorlagen` | Vorlagen-Empfehlung via RAG |
| POST | `/akte/chat` | Loki Akte-Chat |
| GET | `/loki/status` | Loki/Ollama Server-Status |

API-Doku: `http://localhost:5000/docs`

## RAG Collections

| Collection | Inhalt | Laden |
|---|---|---|
| `system_wissen` | Workflow-Dokumente, Falltyp-Abläufe | `scripts/load_system_doku.py` |
| `kanzlei_wissen` | Referenzschreiben, Goldstandard-Briefe | RAG Dashboard im Frontend |
| `akte_dokumente` | Hochgeladene Dokumente je Akte | Automatisch beim Upload |

### system_wissen neu laden:
```bash
docker exec kanzlei-ai-service python scripts/load_system_doku.py
```

## LLM Provider

| Provider | Umgebung | Auth | Modell |
|---|---|---|---|
| `gemini` | Entwicklung | API-Key | gemini-2.5-flash |
| `vertex` | **Produktion** (DSGVO!) | Service Account | gemini-2.5-flash, europe-west3 |
| `loki` | Fallback | — | llama-vision-work + qwen-work |

Logging-Label in Service-Logs: `[LLM: VERTEX AI]` / `[LLM: GEMINI API]`

## Deployment (Produktion)

```bash
# Server: /opt/Kanzlei_AI_Service
git pull
docker compose -f docker-compose.yml --env-file .env.production up -d --build
```

Voraussetzungen Vertex AI:
1. Vertex AI API im GCP-Projekt aktiviert
2. Service Account mit Rolle "Vertex AI User"
3. `google_service_account.json` vorhanden (wird gemountet)
4. `.env.production`: `LLM_PROVIDER=vertex` + `VERTEX_PROJECT_ID` + `VERTEX_LOCATION=europe-west3`

## Lizenz

Proprietär — nur für interne Nutzung.
