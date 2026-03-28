# DocDigest — LLM-Powered Document Analyser

A full-stack application that ingests large books, research papers, legal contracts, and lengthy reports, then produces structured multi-level summaries and enables follow-up Q&A grounded in the source text.

## Features

- **Multi-format ingestion** — PDF, EPUB, DOCX, and plain text with OCR fallback
- **Hierarchical summaries** — Executive brief → Key takeaways → Chapter summaries → Section summaries
- **Follow-up Q&A** — Ask questions grounded in the actual source text with page citations
- **Async processing** — Upload returns immediately; a Celery worker handles the pipeline in the background
- **Model routing** — Uses Sonnet for chunk summaries, Opus for synthesis (configurable)
- **Export** — Download summaries as Markdown
- **Chatbot interface** — Conversational UI: upload, summaries, and Q&A all within a single chat

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite) — Chatbot Interface                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Conversational UI                                         │ │
│  │  File attachment → Processing updates → Summaries → Q&A   │ │
│  │  All interactions through a single chat thread             │ │
│  └──────────────────────────┬─────────────────────────────────┘ │
└─────────────────────────────┼───────────────────────────────────┘
                              │ /api/v1/documents/*
┌──────────────────────────┼───────────────────────┼──────────────┐
│  Backend (FastAPI)       │                       │              │
│  ┌───────────────────────▼───────────────────────▼────────────┐ │
│  │ REST API: upload, status, summary, ask, export, list       │ │
│  └───────────────────────┬────────────────────────────────────┘ │
│                          │ Celery task                          │
│  ┌───────────────────────▼────────────────────────────────────┐ │
│  │ Pipeline: Parse → Chunk → Summarise (Claude) → Embed      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ PostgreSQL +    │  │ Redis        │  │ Anthropic Claude  │  │
│  │ pgvector        │  │ (task queue) │  │ API               │  │
│  └─────────────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
docdigest/
├── app/                          # Python backend
│   ├── main.py                   # FastAPI entry (serves API + built frontend)
│   ├── config.py                 # Settings from environment
│   ├── worker.py                 # Celery tasks (full processing pipeline)
│   ├── models/
│   │   ├── database.py           # SQLAlchemy async engine + session
│   │   └── schemas.py            # ORM models + Pydantic request/response schemas
│   ├── routers/
│   │   └── documents.py          # All REST endpoints
│   └── services/
│       ├── parser.py             # PDF / EPUB / DOCX / TXT parser with OCR
│       ├── chunker.py            # Structure-aware text chunking
│       ├── summariser.py         # Hierarchical map-reduce summarisation
│       ├── embedder.py           # Voyage AI embeddings + dev fallback
│       └── qa_engine.py          # RAG-based Q&A with vector search
├── frontend/                     # React frontend (chatbot interface)
│   ├── src/
│   │   ├── App.jsx               # Entry — renders ChatInterface
│   │   ├── main.jsx              # React mount
│   │   ├── index.css             # Global styles + CSS variables
│   │   ├── services/
│   │   │   └── api.js            # API client (maps 1:1 to backend endpoints)
│   │   ├── hooks/
│   │   │   └── useChatbot.js     # Chat orchestrator: uploads, polling, summaries, Q&A
│   │   └── components/
│   │       └── ChatInterface.jsx # Full chatbot UI with message type renderers
│   ├── index.html
│   ├── vite.config.js            # Dev proxy: /api → localhost:8000
│   └── package.json
├── scripts/
│   └── init_db.py                # Database initialisation
├── tests/
│   ├── test_chunker.py
│   └── test_summariser.py
├── Dockerfile                    # Multi-stage: build frontend + Python app
├── docker-compose.yml            # Full stack: db + redis + api + worker
├── .env.example
├── .dockerignore
├── requirements.txt
└── README.md
```

## Quick Start

### Option A: Docker Compose (recommended)

The fastest way to run the full stack with one command.

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY

# 2. Launch everything
docker compose up --build

# 3. Open in browser
open http://localhost:8000
```

This starts PostgreSQL (with pgvector), Redis, the FastAPI server, and the Celery worker. The frontend is built during the Docker image build and served by FastAPI.

### Option B: Local development (separate terminals)

For active development with hot reload on both frontend and backend.

**Prerequisites:** Python 3.11+, Node.js 18+, PostgreSQL 15+ (with pgvector), Redis.

```bash
# 1. Backend setup
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your keys and database URL

# 2. Database setup
createdb docdigest
psql docdigest -c "CREATE EXTENSION IF NOT EXISTS vector;"
python -m scripts.init_db

# 3. Frontend setup
cd frontend
npm install
cd ..

# 4. Start services (four terminals)

# Terminal 1 — Backend API (port 8000)
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Celery worker
celery -A app.worker worker --loglevel=info --concurrency=4

# Terminal 3 — Frontend dev server (port 3000, proxies /api → 8000)
cd frontend && npm run dev

# Terminal 4 (optional) — Celery Flower monitoring
celery -A app.worker flower --port=5555
```

In dev mode, open **http://localhost:3000** (Vite dev server with hot reload).

### Option C: Production build (single server)

Build the frontend, then serve everything from FastAPI:

```bash
# Build frontend
cd frontend && npm install && npm run build && cd ..

# Start API (serves both API + built frontend)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start worker (separate process)
celery -A app.worker worker --loglevel=info --concurrency=4
```

Open **http://localhost:8000** — FastAPI serves the React app and API from the same origin.

## Frontend ↔ Backend Integration

### API Client Mapping

The frontend communicates through a typed API client (`frontend/src/services/api.js`) that maps directly to every FastAPI endpoint:

| Frontend call             | HTTP request                             | Backend handler               |
| ------------------------- | ---------------------------------------- | ----------------------------- |
| `uploadDocument(file)`    | `POST /api/v1/documents/upload`          | `documents.upload_document`   |
| `getStatus(id)`           | `GET /api/v1/documents/{id}/status`      | `documents.get_status`        |
| `getSummary(id, level)`   | `GET /api/v1/documents/{id}/summary`     | `documents.get_summary`       |
| `askQuestion(id, q)`      | `POST /api/v1/documents/{id}/ask`        | `documents.ask`               |
| `exportSummary(id, lvl)`  | `GET /api/v1/documents/{id}/export`      | `documents.export_summary`    |
| `listDocuments()`         | `GET /api/v1/documents`                  | `documents.list_documents`    |
| `deleteDocument(id)`      | `DELETE /api/v1/documents/{id}`          | `documents.delete_document`   |

### Data Flow (Chatbot)

All interactions happen within a single conversational thread:

1. **Welcome** → Bot greets user, offers action buttons ("Upload a document" / "What can you do?")
2. **Upload** → User attaches file via paperclip or drag-and-drop → `POST /upload` → bot shows a live-updating status card polling `GET /status` every 2s
3. **Summary delivery** → On "completed", bot automatically fetches the executive brief via `GET /summary?level=brief` and delivers it as a rich summary card with action buttons for other levels
4. **Exploring** → User clicks "Key takeaways" or "Chapters" → bot fetches `GET /summary?level=takeaways|chapters` and renders styled cards
5. **Q&A** → Any free-text message while a document is loaded → `POST /ask` → bot responds with the answer and page-citation tags
6. **Export** → User clicks "Export as Markdown" or types "export" → `GET /export` → triggers a file download
7. **New document** → User types "upload another" or attaches a new file → resets context

### Development Proxy

During development, Vite (port 3000) proxies `/api/*` and `/health` to FastAPI (port 8000) via `frontend/vite.config.js`. In production, FastAPI serves both the API and the built frontend from the same origin.

## Configuration

All settings in `app/config.py`, overridable via `.env`:

| Variable              | Default                      | Description                         |
| --------------------- | ---------------------------- | ----------------------------------- |
| `ANTHROPIC_API_KEY`   | —                            | Your Anthropic API key              |
| `DATABASE_URL`        | `postgresql+asyncpg://...`   | PostgreSQL connection string        |
| `REDIS_URL`           | `redis://localhost:6379/0`   | Redis connection string             |
| `UPLOAD_DIR`          | `./uploads`                  | Where uploaded files are stored     |
| `CHUNK_TARGET_TOKENS` | `1000`                       | Target tokens per chunk             |
| `CHUNK_OVERLAP_TOKENS`| `100`                        | Overlap tokens between chunks       |
| `SUMMARY_MODEL`       | `claude-sonnet-4-20250514`   | Model for chunk-level summaries     |
| `SYNTHESIS_MODEL`     | `claude-opus-4-20250514`     | Model for merge / synthesis steps   |
| `EMBEDDING_MODEL`     | `voyage-3`                   | Embedding model for vector search   |
| `QA_TOP_K`            | `5`                          | Chunks retrieved for RAG answers    |

## License

MIT
