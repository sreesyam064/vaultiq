<div align="center">

# 🧠 VaultIQ

### Personal Knowledge Base Assistant

**Upload your PDFs. Ask questions. Get intelligent answers.**

A production-grade RAG (Retrieval-Augmented Generation) application built with Flask, ChromaDB, LangChain, and Streamlit.

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)](https://flask.palletsprojects.com)
[![LangChain](https://img.shields.io/badge/LangChain-latest-green)](https://langchain.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-latest-orange)](https://chromadb.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-latest-red?logo=streamlit)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

[Overview](#overview) • [Features](#key-features) • [Tech Stack](#tech-stack) • [Setup](#installation--setup) • [Testing](#testing) • [Deployment](#cicd--deployment)

</div>

---

## Overview

VaultIQ is a production-grade Personal Knowledge Base Assistant that lets users upload PDF documents and ask intelligent questions about them in natural language. It combines a Flask REST API backend, a ChromaDB vector store, a LangChain RAG pipeline, and a Streamlit frontend into a fully deployable application.

The project was built as a portfolio piece demonstrating end-to-end ML system design — from PDF ingestion and embedding to intelligent query routing, multi-user isolation, JWT authentication, rate limiting, structured logging, a 120-test pytest suite and GitHub Actions CI/CD, and Docker containerization.

---

## Key Features

- **PDF ingestion pipeline** — upload multiple PDFs, automatically chunked and embedded into a persistent vector store with per-user isolation
- **Intelligent query routing** — detects query intent and applies the optimal retrieval strategy for each type:
  - `summarize` → direct chunk fetch for document overview
  - `compare` → broad multi-chunk fetch for topic comparison
  - `concepts` → concept-focused retrieval
  - `interview` → structured Q&A generation
  - `factual` → similarity search with adaptive threshold
- **Adaptive retrieval** — dynamic K scaling based on collection size, adaptive relevance threshold that adjusts to document density, tiny-doc shortcut for short documents
- **Source-aware filtering** — detects filename references in queries and restricts retrieval to that document
- **Multi-session chat** — create, switch, and search named chat sessions with full history
- **Page-level citations** — every answer includes source filename and page number
- **LLM provider abstraction** — Ollama locally, OpenRouter (free tier) in production
- **4-model fallback chain** — if primary model is rate-limited, automatically tries backup → fallback → emergency
- **Production hardening** — JWT auth, rate limiting, config validation at startup, retry/timeout on all LLM calls, rotating file logging, `/health` and `/health/deep` endpoints
- **Structured JSON logging** — every log line carries `request_id`, `user_id`, timestamp, and processing time, auto-attached with zero per-call effort
- **Global error handling** — every failure mode (upload, embedding, vector DB, LLM, and anything unexpected) returns a consistnet JSON error; raw exceptions never reach the client.
- **120-test pytest suite** — unit, integration, and route tests across 3 tiers

---

## Tech Stack

| Layer                | Technology                                                       |
| -------------------- | ---------------------------------------------------------------- |
| **Backend**          | Flask, Flask-JWT-Extended, Flask-Limiter, Flask-SQLAlchemy       |
| **RAG Pipeline**     | LangChain, ChromaDB, `all-MiniLM-L6-v2` embeddings (HuggingFace) |
| **LLM — local dev**  | Ollama (`qwen2.5:3b`)                                            |
| **LLM — production** | OpenRouter free tier with 4-model fallback chain                 |
| **Frontend**         | Streamlit                                                        |
| **Database**         | SQLite (via SQLAlchemy)                                          |
| **Auth**             | JWT (Flask-JWT-Extended)                                         |
| **Testing**          | pytest, pytest-mock                                              |
| **CI/CD**            | GitHub Actions                                                   |
| **Containerization** | Docker, Docker Compose                                           |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User Browser                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼──────────────────────────────────┐
│                   Streamlit Frontend                        │
│   Login / Register / Upload / Chat / Session History        │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API (JWT)
┌──────────────────────────▼──────────────────────────────────┐
│                    Flask Backend (gunicorn)                 │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Auth Routes │  │ Upload Routes│  │   Chat Routes      │  │
│  │ /register   │  │ /upload      │  │ /ask  /chat/*      │  │
│  │ /login      │  │              │  │ /chat/session      │  │
│  └─────────────┘  └──────┬───────┘  └────────┬───────────┘  │
│                          │                   │              │
│                   ┌──────▼───────────────────▼───────────┐  │
│                   │          RAG Service                 │  │
│                   │                                      │  │
│                   │  1. _detect_query_type()             │  │
│                   │  2. _extract_source_filter()         │  │
│                   │  3. Tiny-doc shortcut / MMR search   │  │
│                   │  4. Adaptive relevance threshold     │  │
│                   │  5. Context + prompt building        │  │
│                   │  6. LLM call with fallback chain     │  │
│                   └──────┬───────────────────────────────┘  │
│                          │                                  │
│            ┌─────────────┼─────────────┐                    │
│            │             │             │                    │
│     ┌──────▼───┐  ┌──────▼─────┐  ┌────▼──────┐             │
│     │  SQLite  │  │  ChromaDB  │  │  Ollama   │             │
│     │  (auth,  │  │  (vectors) │  │ OpenRouter│             │
│     │ sessions)│  │            │  │  (LLM)    │             │
│     └──────────┘  └────────────┘  └───────────┘             │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
vaultiq/
├── .env.example                    # Environment variable template
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt                # Root-level deps
├── requirements-dev.txt            # Dev/test deps
├── docker-compose.dev.yml          # Dev — self-contained (Ollama, debug mode,no restart on crash)
├── docker-compose.prod.yml         # Prod — self-contained (OpenRouter, 450MB limits, restart always)
├── .env.dev.example                # Dev env template (copy to .env.dev, fill in secrets)
├── .env.prod.example               # Prod env template (copy to .env.prod, fill in secrets)
│
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions pipeline
│
├── backend/
│   ├── app.py                      # Flask app factory, blueprint registration
│   ├── config.py                   # Config + startup validation
│   ├── gunicorn.conf.py            # Gunicorn config for backend
│   ├── llm_provider.py             # LLM factory + 4-model OpenRouter fallback chain
│   ├── logging_config.py           # Rotating file logging setup
│   ├── init_db.py                  # Initialize the database
│   ├── Dockerfile                  # python:3.12-slim, gunicorn, model pre-baked
│   ├── .dockerignore
│   ├── requirements.txt            # Backend-only deps
│   ├── pytest.ini                  # Test config + warning filters
│   ├── wsgi.py                     # Entrypoint for Gunicorn (Docker prod only) + initialize db + eager model warmup
│   │
│   ├── extensions/                 # Flask extensions
│   │   ├── db.py                   # SQLAlchemy
│   │   ├── jwt.py                  # JWT
│   │   └── limiter.py              # Rate limiter (JWT-keyed, not IP-keyed)
│   │
│   ├── models/                     # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── document.py
│   │   └── chat.py                 # ChatSession + Message
│   │
│   ├── routes/                     # Flask blueprints
│   │   ├── auth_routes.py          # /register /login /logout
│   │   ├── upload_routes.py        # /upload (duplicate guard, ingest trigger)
│   │   ├── chat_routes.py          # /ask /chat/session /chat/sessions
│   │   └── health_routes.py        # /health (liveness) /health/deep (deps + log sizes)
│   │
│   ├── services/
│   │   └── rag_service.py          # Full RAG pipeline (ingest, route, retrieve, answer)
│   │
│   ├── tests/
│   │   ├── conftest.py             # Shared fixtures
│   │   ├── fixtures/
│   │   │   └── sample.pdf          # 3-page test PDF
│   │   ├── test_unit_config.py     # Tier 1 — config validation
│   │   ├── test_unit_rag.py        # Tier 1 — query router, retry, fallback, threshold, K
│   │   ├── test_integration_rag.py # Tier 2 — real Chroma + fixture PDF, mocked LLM
│   │   └── test_routes.py          # Tier 3 — Flask test client, auth, validation
│   │
│   └── storage/                    # Runtime data — gitignored except .gitkeep files
│       │                           # Auto-recreated with .gitkeep on every app startup
│       ├── uploads/                # Uploaded PDFs
│       │   └── .gitkeep
│       ├── vector_db/
│       │    └── chroma_db/         # ChromaDB embeddings
│       │        └── .gitkeep
│       ├── database/
│       │   ├── rag.db              # SQLite — users, sessions, messages, documents
│       │   └── .gitkeep
│       └── logs/                   # Rotating log files (5MB each, 5 backups)
│           ├── app.log             # INFO+ — all application activity
│           ├── error.log           # WARNING+ — failures and exceptions only
│           ├── access.log          # HTTP access log (all requests via werkzeug)
│           └── .gitkeep
│
└── frontend/
    ├── app.py                      # Streamlit entry point (login page)
    ├── Dockerfile                  # python:3.12-slim, curl, config.toml
    ├── .dockerignore
    ├── requirements.txt            # Frontend-only deps (streamlit, requests)
    ├── .streamlit/
    │   └── config.toml             # VaultIQ dark theme + production server config
    ├── pages/
    │   ├── chat.py                 # Main chat interface
    │   ├── upload.py               # PDF upload with duplicate feedback
    │   └── register.py             # USer registration
    ├── components/
    │   ├── initialize_chat.py      # Session state + backend session creation
    │   ├── sidebar.py              # Session history, search, nav buttons
    │   ├── welcome.py              # Welcome screen + 4 suggested questions
    │   ├── messages.py             # Chat message renderer
    │   └── question_input.py       # Chat input + suggested question handler
    └── utils/
        └── api.py                  # Backend REST client (BACKEND_URL configurable)
```

---

## RAG Pipeline

```
PDF Upload
    │
    ▼
PyPDFLoader → RecursiveCharacterTextSplitter
              chunk_size=1000, overlap=200
    │
    ▼
HuggingFace Embeddings (all-MiniLM-L6-v2, 384 dims)
    │
    ▼
ChromaDB — stored with metadata:
           source, user_id, document_id, chunk_id, page, total_chunks
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                   Query Routing                     │
│                                                     │
│  _detect_query_type()  →  summarize / compare /     │
│                           concepts / interview /    │
│                           factual                   │
│                                                     │
│  _extract_source_filter()  →  restrict to named doc │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
  Broad query             Factual query
  (summarize/             (specific Q&A)
  compare/concepts/
  interview)                    │
       │                   Tiny doc? (≤15 chunks)
       │                   Yes → fetch all chunks
       ▼                   No  → MMR retrieval
  Direct chunk                  │
  fetch (no                 Adaptive threshold
  similarity search)        mean + (max-mean)*0.5
                            bounded [0.10, 0.40]
       │                        │
       └───────────┬────────────┘
                   │
                   ▼
           Task-specific prompt
           (different instruction per query type)
                   │
                   ▼
          LLM via fallback chain (OpenRouter production)
          ┌─────────────────────────────────────────┐
          │ Primary   → google/gemma-4-31b-it:free  │
          │ Backup    → openai/gpt-oss-120b:free    │
          │ Fallback  → openai/gpt-oss-20b:free     │
          │ Emergency → openrouter/free             │
          └─────────────────────────────────────────┘
                   │
                   ▼
        Answer + page-level citations
```

---

## API Endpoints

| Method | Endpoint         | Auth | Description                                                    |
| ------ | ---------------- | ---- | -------------------------------------------------------------- |
| `POST` | `/register`      | No   | Register new user                                              |
| `POST` | `/login`         | No   | Login, returns JWT token                                       |
| `GET`  | `/profile`       | JWT  | Get current user info                                          |
| `POST` | `/upload`        | JWT  | Upload one or more PDFs                                        |
| `POST` | `/chat/session`  | JWT  | Create new chat session                                        |
| `GET`  | `/chat/sessions` | JWT  | List all sessions (with titles)                                |
| `GET`  | `/chat/<id>`     | JWT  | Get full message history for session                           |
| `POST` | `/ask`           | JWT  | Ask a question — triggers RAG pipeline                         |
| `GET`  | `/health`        | No   | Liveness check (Flask + DB)                                    |
| `GET`  | `/health/deep`   | No   | Dependency check (Chroma, SQLite, LLM config, log files sizes) |

**Rate limiting:** `/ask` is limited to `10 per minute` per authenticated user (JWT-keyed, not IP-keyed — configurable via `ASK_RATE_LIMIT` env var) to protect OpenRouter free-tier quota.

---

## Installation & Setup

### Prerequisites

- Python 3.12+
- [Ollama](https://ollama.ai) installed and running (local dev only)
- Git

### 1. Clone the repository

```bash
git clone https://github.com/sreesyam064/vaultiq.git
cd vaultiq
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Pull the local LLM model

```bash
ollama pull qwen2.5:3b
```

### 5. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
SECRET_KEY=<generate below>
JWT_SECRET_KEY=<generate below>
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
```

Generate secure keys:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 6. Run the backend

```bash
cd backend
python app.py
# Flask runs at http://127.0.0.1:5000
```

### 7. Run the frontend

```bash
cd frontend
streamlit run app.py
# Streamlit runs at http://localhost:8501
```

---

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable              | Required    | Default                  | Description                                           |
| --------------------- | ----------- | ------------------------ | ----------------------------------------------------- |
| `SECRET_KEY`          | ✅          | —                        | Flask session secret                                  |
| `JWT_SECRET_KEY`      | ✅          | —                        | JWT signing key                                       |
| `LLM_PROVIDER`        | ✅          | `ollama`                 | `ollama` or `openrouter`                              |
| `LLM_MODEL`           | ✅          | `qwen2.5:3b`             | Model ID for the active provider                      |
| `OPENROUTER_API_KEY`  | Prod only   | —                        | From [openrouter.ai/keys](https://openrouter.ai/keys) |
| `OLLAMA_HOST`         | Docker only | `http://localhost:11434` | Ollama server URL                                     |
| `BACKEND_URL`         | Docker/Prod | `http://127.0.0.1:5000`  | Backend URL for frontend                              |
| `LLM_TIMEOUT_SECONDS` | No          | `30`                     | Per-request LLM timeout                               |
| `LLM_MAX_RETRIES`     | No          | `2`                      | Retries before fallback triggers                      |
| `ASK_RATE_LIMIT`      | No          | `10 per minute`          | Rate limit on `/ask` per user                         |
| `CHUNK_SIZE`          | No          | `1000`                   | PDF chunk size in tokens                              |
| `CHUNK_OVERLAP`       | No          | `200`                    | Chunk overlap in tokens                               |
| `RETRIEVAL_K`         | No          | `5`                      | Base number of chunks to retrieve                     |
| `LOG_LEVEL`           | No          | `INFO`                   | Logging level                                         |

---

## Usage Guide

### 1. Register and login

Open `http://localhost:8501`, create an account, and login.

### 2. Upload documents

Click **Upload Documents** in the sidebar. Select one or more PDFs. VaultIQ will ingest, chunk, and embed them automatically. Duplicate uploads are detected and skipped.

### 3. Ask questions

Use the welcome screen's suggested questions or type your own:

- **"Summarize the uploaded documents"** — structured document summary
- **"Compare the main topics discussed"** — topic comparison with headings
- **"Explain the important concepts"** — concept list with definitions
- **"Generate interview questions"** — 6 Q&A pairs from document content
- **"What is backpropagation?"** — specific factual lookup
- **"Tell me about the resume.pdf"** — file-specific query (auto-filters to that doc)

### 4. Manage sessions

Create multiple chat sessions from the sidebar. Each session has its own history. Click any session to switch to it. Search through session history with the search box.

### 5. View logs

Check application activity anytime via:

```bash
# All activity (INFO+)
tail -f backend/storage/logs/app.log

# Errors only (WARNING+)
tail -f backend/storage/logs/error.log

# HTTP traffic
tail -f backend/storage/logs/access.log
```

Or via the API:

```
GET /health/deep
# Returns log files sizes under "checks.log_files"
```

### 6. Reset storage

Delete `backend/storage` to clear all uploads, ChromaDB, and SQLite. On next app start, the directory structure and `.gitkeep` files are automatically recreated by `config.py`.

---

## Testing

VaultIQ has a 3-tier test suite with **120 tests**.

### Tier 1 — Unit tests (fast, no external dependencies)

```bash
cd backend
pytest tests/test_unit_config.py tests/test_unit_rag.py -v
```

Covers: config validation, query type detection, retry logic, fallback chain, adaptive threshold, dynamic K, source filter helper, provider factory, and retrieval-layer error handling (vector store open failures and similarity search failures degrade gracefully instead of propagating).

### Tier 2 — Integration tests (real Chroma, mocked LLM)

```bash
pytest tests/test_integration_rag.py -v
```

Covers: real PDF ingestion, chunk metadata, user isolation, duplicate guard, broad query retrieval, factual retrieval, citation building, LLM failure handling.

> Requires HuggingFace embedding model download (~90MB on first run). Run locally before pushing — excluded from CI to keep pipeline fast.

### Tier 3 — Route tests (Flask test client)

```bash
pytest tests/test_routes.py -v
```

Covers: auth flow, duplicate upload detection, session ownership enforcement, input validation, health endpoints, rate limiting, and global error handlers (JSON 404/405, and a full round-trip confirming an unexpected exception returns a clean JOSN 500 with real exception message never leaking to client).

### Full suite

```bash
pytest tests/ -v
# 120 passed
```

### Test architecture

| Tier            | File                    | Tests   | External deps                | Runs in CI    |
| --------------- | ----------------------- | ------- | ---------------------------- | ------------- |
| 1 — Unit        | test_unit_config.py     | 6       | None                         | ✅            |
| 1 — Unit        | test_unit_rag.py        | 68      | None                         | ✅            |
| 2 — Integration | test_integration_rag.py | 15      | HuggingFace, ChromaDB        | ❌ local only |
| 3 — Routes      | test_routes.py          | 31      | Flask only (mocked services) | ✅            |
| **Total**       |                         | **120** |                              |               |

---

## Security Considerations

- **JWT authentication** on all protected routes with token expiry
- **Per-user data isolation** — ChromaDB queries are always filtered by `user_id`; one user can never access another's documents or chat history
- **Rate limiting** on `/ask` keyed by JWT identity (not IP) — prevents free-tier LLM quota exhaustion by a single user
- **Config validation at startup** — app refuses to boot with missing secrets or invalid provider config rather than failing silently mid-request
- **No secrets in Docker image** — `.env` is in `.dockerignore`; all secrets injected via environment variables at runtime
- **Password hashing** via Werkzeug's `generate_password_hash` / `check_password_hash`
- **Session ownership check** — users can only read their own chat sessions (404 on others)
- **Rotating log files** — bounded at ~150MB total, logs never contain passwords or JWT tokens

---

## Performance Optimizations

- **Lazy singleton initialization** — embedding model and LLM client are loaded on first request, not at import time, so importing any module for testing doesn't trigger model downloads
- **Dynamic K retrieval** — `k = min(10, max(3, total_chunks // 30))` scales the retrieval pool with collection size rather than using a fixed value
- **Adaptive relevance threshold** — `threshold = mean + (max - mean) * 0.5` adjusts to each query's score distribution, preventing noise on large docs and over-filtering on small ones
- **Tiny-doc shortcut** — documents with ≤15 chunks bypass similarity search entirely (fetches all chunks directly) since sparse embedding spaces produce unreliable cosine similarities
- **Source-aware filtering** — when a filename is mentioned in the query, ChromaDB is filtered to that document only, eliminating cross-document score pollution
- **Minimal chroma fetches** — metadata-only lookups (filename detection, chunk counting) use `include=["metadatas]` / `include=[]` instead of the default, which otherwise pulls full document text for the entire collection on every single query regardless of relevance
- **MMR retrieval** — Maximal Marginal Relevance diversifies retrieved chunks so the LLM receives a broader document cross-section rather than near-identical paragraphs
- **HuggingFace model pre-baked into Docker image** — prevents 30-60 second cold-start delay on first request after deploy
- **Eager model warm-up via `wsgi.py` + gunicorn `preload_app`** — embedding model and LLM client load once in the master process before forking. workers share them via copy-on-write instead of each loading a separate copy
- **Gunicorn 2 workers** — production WSGI server; capped at 2 to fit Render free-tier RAM (each worker holds the embedding model in memory ~500MB)

---

## Known Limitations

- **Local Ollama generation time on long-form answers (dev environment only)** `qwen2.5:3b` running on CPU via Ollama generates output proportionally to requested length, not just input/context size. Query types that explicitly ask for long, multi-part output — `interview` (6 full Q&A pairs), or a `factual`/`summarize` question phrased as "explain each type in detailed with examples" — can exceed even a generous gunicorn worker timeout (300s in dev) on typical development hardware. Shorter or more direct questions complete comfortably within 1-3 minutes.
  - This is a **dev-only** limitation. Production uses OpenRouter's hosted inference (`google/gemma-4-31b-it:free` and its fallback chain), which is dramatically faster than local CPU-bound Ollama and does not exhibit this behaviour.
  - No code changes are needed to work around this for local testing — prefer more direct/scoped questions when testing against Ollama, or expect longer waits on deliberately verbose prompts.

---

## CI/CD & Deployment

### CI Pipeline (GitHub Actions)

Triggers on every push and pull request to `main`.

```
push / PR
    │
    ▼
1. Lint (ruff)          ~10s   — syntax errors, unused imports, undefined names
    │ passes
    ▼
2. Test (pytest)        ~30s   — Tier 1 + Tier 3, mocked LLM, no API keys needed
    │ passes
    │
    ├── PR / feature branch -> STOP (no deploy)
    │
    └── push to main only
            │
            ▼
        3. Deploy (Render hook)
           Fires RENDER_DEPLOY_HOOK_URL secret
           Render pulls latest main and redeployes
```

Render's built-in GitHub integration is intentionally **disabled** — the deploy hook in CI ensures Render only receives a deploy signal after lint and tests both pass.

### Running with Docker (dev and prod environments)

VaultIQ has two self-contained compose files — one for development and one for production. Each file is fully independent with no shared base. Switch environments by changingone command, nothing else.

```
docker-compose.dev.yml     dev — Ollama, DEBUG logging, no restart on crash
docker-compose.prod.yml    prod — OpenRouter, INFO logging, memory limit, restart always
.env.dev                   dev secrets (only SECRET_KEY + JWT_SECRET_KEY needed)
.env.prod                ← prod secrets (add OPENROUTER_API_KEY)
```

**Setup — first time only:**

```bash
cp .env.dev.example  .env.dev    # fill in SECRET_KEY + JWT_SECRET_KEY
cp .env.prod.example .env.prod   # fill in SECRET_KEY + JWT_SECRET_KEY + OPENROUTER_API_KEY
```

**Development (Ollama — no API key needed):**

```bash
# First time: pull the Ollama model
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d ollama
docker exec vaultiq_ollama ollama pull qwen2.5:3b

# Start
docker compose -f docker-compose.dev.yml --env-file .env.dev up --build

# Stop
docker compose -f docker-compose.dev.yml down
```

**Production simulation (OpenRouter —tests prod config locally before deploying):**

```bash
# Start
docker compose -f docker-compose.prod.yml --env-file .env.prod up --build

# Stop
docker compose -f docker-compose.prod.yml down
```

**Key differences per environment:**

| Setting         | Dev                                          | Prod                                   |
| --------------- | -------------------------------------------- | -------------------------------------- |
| LLM             | Ollama `qwen2.5:3b`                          | OpenRouter `gemma-4-31b-it:free`       |
| Ollama service  | ✅ Included                                  | ❌ Not needed (API call)               |
| LOG_LEVEL       | DEBUG                                        | INFO                                   |
| LLM timeout     | 120s (local CPU inference is slow)           | 30s (API calls are fast)               |
| Retries         | 1                                            | 2                                      |
| Rate limit      | 100/min (no quota to protect)                | 10/min (protects OpenRouter free tier) |
| Restart policy  | `no` (stay stopped on crash to inspect logs) | `unless-stopped` (auto-recover)        |
| Memory limit    | None                                         | 450MB (fits Render free tier 512MB)    |
| Volume name     | `vaultiq_backend_storage_dev`                | `vaultiq_backend_storage_prod`         |
| Container names | `vaultiq_backend_dev`                        | `vaultiq_backend_prod`                 |

Dev and prod use **separate named volumes** so their data (uploads, ChromaDB, SQLite, logs) never mix even when run on the same machine. You can have both environments data on disk simultaneously.

---

## Project Status

| Phase                                 | Status      |
| ------------------------------------- | ----------- |
| Backend (Flask API + RAG pipeline)    | ✅ Complete |
| Frontend (Streamlit)                  | ✅ Complete |
| Test suite (112 tests, 3 tiers)       | ✅ Complete |
| CI/CD (GitHub Actions)                | ✅ Complete |
| Docker (backend + frontend + compose) | ✅ Complete |
| Deployment (Render)                   | 🔜 Planned  |
| Persistent storage upgrade            | 🔜 Planned  |

---

## Future Improvements

### Persistent Storage (Priority)

The current deployment uses Render's ephemeral filesystem — all data is wiped on redeploy and after 15 minutes of inactivity on free tier. The planned upgrade replaces all three storage layers with permanent free-tier cloud services:

| Layer        | Current              | Planned                                                                     | Why                                        |
| ------------ | -------------------- | --------------------------------------------------------------------------- | ------------------------------------------ |
| Database     | SQLite (local file)  | [Supabase](https://supabase.com) PostgreSQL                                 | Free managed Postgres, 500MB, never wiped  |
| Vector store | ChromaDB (local dir) | [Qdrant Cloud](https://qdrant.tech)                                         | Free managed vector DB, 1GB, persistent    |
| File storage | Local filesystem     | [Cloudflare R2](https://cloudflare.com/r2) or Supabase Storage or Amazon S3 | Free object storage (R2: 10GB), CDN-backed |

### Other Improvements

- **Streaming LLM responses** — pipe token stream from OpenRouter to Streamlit for real-time output
- **Re-ranking** — add a cross-encoder re-ranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) after MMR retrieval for higher precision
- **Multi-modal support** — extract and embed images, tables, and diagrams from PDFs (not just text)
- **Conversation-aware retrieval** — include recent chat history in the retrieval query for multi-turn follow-up questions
- **Document collections** — let users organise documents into named collections and query within a collection
- **Export** — download chat history as PDF or Markdown

## Acknowledgements

- [LangChain](https://langchain.com) — RAG pipeline framework
- [ChromaDB](https://trychroma.com) — vector store
- [Sentence Transformers](https://sbert.net) — `all-MiniLM-L6-v2` embedding model
- [OpenRouter](https://openrouter.ai) — unified LLM API gateway
- [Ollama](https://ollama.ai) — local LLM inference
- [Streamlit](https://streamlit.io) — frontend framework
- [Render](https://render.com) — deployment platform

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Author

**Pathakota Megha Sri Syam**

- 📧 sreesyam064@gmail.com
- 📍 Vijayawada, Andhra Pradesh
- 🔗 [GitHub](https://github.com/sreesyam064)
- 💼 [LinkedIn](https://linkedin.com/in/sree-syam)

_Actively seeking roles as ML Engineer / AI Engineer / Full-Stack + AI Developer_

---

<div align="center">

Built with ❤️ as a production-grade portfolio project

⭐ Star this repo if you found it useful

</div>
