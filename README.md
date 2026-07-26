<div align="center">
# 🧠 VaultIQ

### Personal Knowledge Base Assistant

**Upload your PDFs. Ask questions. Get intelligent answers.**

A production-grade RAG (Retrieval-Augmented Generation) application built with Flask, ChromaDB, LangChain, and Streamlit.

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)](https://flask.palletsprojects.com)
[![LangChain](https://img.shields.io/badge/LangChain-latest-green)](https://langchain.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-latest-orange)](https://chromadb.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-blue?logo=postgresql)](https://neon.tech)
[![Streamlit](https://img.shields.io/badge/Streamlit-latest-red?logo=streamlit)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

[Overview](#overview) • [Features](#key-features) • [Tech Stack](#tech-stack) • [Setup](#installation--setup) • [Testing](#testing) • [Deployment](#cicd--deployment)

#### 🌐 Live Demo: 🔗 https://vault-iq.in

</div>

---

## Overview

VaultIQ is a production-grade Personal Knowledge Base Assistant that lets users upload PDF documents and ask intelligent questions about them in natural language. It combines a Flask REST API backend, a ChromaDB vector store, a LangChain RAG pipeline, and a Streamlit frontend into a fully deployable application — running in production on AWS EC2 behind Nginx, backed by managed PostgreSQL (Neon) and Cloudflare R2 objcet storage rather than local files.

The project was built as a portfolio piece demonstrating end-to-end ML system design — from PDF ingestion and embedding to intelligent query routing, multi-user isolation, JWT authentication, rate limiting, structured logging, a database migration to managed PostgreSQL, a move from local disk to S3-compatible object storage, a 149-case pytest suite, and GitHub Actions CI/CD, and Docker containerization.

---

## Key Features

- **PDF ingestion pipeline** — upload multiple PDFs, automatically chunked and embedded into a persistent vector store with per-user isolation
- **Document lifecycle tracking** — every uploaded document has an explicit `processing` / `ready` / `failed` status; a document is only visible or queryable once every step (Postgres row, Chroma vectors, object storage) has actually succeeded, and any partial failure is compensated (Chroma vectors and storage objects are cleaned up automatically) rather than left as an orphaned, half-uploaded record
- **Cloud-native persistence** — PostgreSQL (Neon) for relational data via Alembic-managed migrations, and Cloudflare R2 (S3-compatible) for uploaded files, replacing the original SQLite/local-disk setup so data survives redeploys and container restarts
- **Document management endpoints** — list your documents and delete one (Postgres row + Chroma vectors + storage object, deleted together, safely retryable if any single step fails)
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
- **Structured JSON logging, Docker-native** — every log line is a single JSON object with `request_id`/`user_id` correctly attached from _any_ module (not just the ones logging directly to root), streamed to stdout/stderr — the authoritative log destination under Gunicorn, with no multi-process file-rotation hazard
- **Global error handling** — every failure mode (upload, embedding, vector DB, LLM, and anything unexpected) returns a consistnet JSON error; raw exceptions never reach the client.
- **149-case test suite (147 run, 2 deselected)** — unit, integration, and route tests, including a real-Gunicorn-subprocess test proving logging survives `preload` + worker forking

---

## Tech Stack

| Layer                    | Technology                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------ |
| **Backend**              | Flask, Flask-JWT-Extended, Flask-Limiter, Flask-SQLAlchemy , Flask-Migrate                             |
| **RAG Pipeline**         | LangChain, ChromaDB, `all-MiniLM-L6-v2` embeddings (HuggingFace)                                       |
| **LLM — local dev**      | Ollama (`qwen2.5:3b`)                                                                                  |
| **LLM — production**     | OpenRouter free tier with 4-model fallback chain                                                       |
| **Frontend**             | Streamlit                                                                                              |
| **Database**             | PostgreSQL via [Neon](https://neon.tech) (prod), SQLite fallback (dev)                                 |
| **Migrations**           | Alembic via Flask-Migrate                                                                              |
| **File storage**         | Cloudflare R2 (S3-compatible, via `boto3`) (prod), local disk fallback (dev)                           |
| **Vector store**         | ChromaDB — persisted on a dedicated AWS EBS volume in production                                       |
| **Auth**                 | JWT (Flask-JWT-Extended)                                                                               |
| **Logging**              | Structured JSON to stdout/stderr (Docker-native); optional rotating files for local single-process dev |
| **Testing**              | pytest, pytest-mock                                                                                    |
| **CI/CD**                | GitHub Actions                                                                                         |
| **Containerization**     | Docker, Docker Compose                                                                                 |
| **Compute (production)** | AWS EC2 (`t4g.small`, ARM/Graviton, Ubuntu 24.04 LTS)                                                  |
| **Reverse proxy / TLS**  | Nginx + Let's Encrypt (Certbot)                                                                        |
| **Container registry**   | GitHub Container Registry (GHCR)                                                                       |
| **Host hardening**       | AWS Security Groups, UFW, Fail2Ban, key-only SSH (password auth disabled)                              |

---

## Architecture

```
                        Internet
                           │
                           ▼
                      GoDaddy DNS
                     (vault-iq.in)
                           │
                           ▼
                      Elastic IP
                           │
┌──────────────────────────▼──────────────────────────────────┐
│          Nginx — TLS termination (Let's Encrypt)            │
│         AWS EC2 (t4g.small, Ubuntu 24.04 LTS ARM)           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   Streamlit Frontend                        │
│   Login / Register / Upload / Chat / Session History        │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API (JWT)
┌──────────────────────────▼────────────────────────────────────────────┐
│                    Flask Backend (gunicorn)                           │
│                                                                       │
│  ┌─────────────┐  ┌────────────────────────┐  ┌────────────────────┐  │
│  │ Auth Routes │  │     Upload Routes      │  │   Chat Routes      │  │
│  │ /register   │  │ /upload                │  │ /ask  /chat/*      │  │
│  │ /login      │  │ /documents (GET/DELETE)│  │ /chat/session      │  │
│  └─────────────┘  └──────┬─────────────────┘  └─────┬──────────────┘  │
│                          │                          │                 │
│                   ┌──────▼──────────────────────────▼────┐            │
│                   │          RAG Service                 │            │
│                   │                                      │            │
│                   │  1. _detect_query_type()             │            │
│                   │  2. _extract_source_filter()         │            │
│                   │  3. Tiny-doc shortcut / similarity   │            │
│                   │  4. Adaptive relevance threshold     │            │
│                   │  5. Context + prompt building        │            │
│                   │  6. LLM call with fallback chain     │            │
│                   └──────┬───────────────────────────────┘            │
│                          │                                            │
│            ┌─────────────┼───────────────┬─────────────┐              │
│            │             │               │             │              │
│     ┌──────▼─────┐  ┌────▼───────┐  ┌────▼──────┐ ┌────▼──────┐       │
│     │  PostgreSQL│  │ ChromaDB   │  │ Cloudflare│ │ Ollama    │       │
│     │  (Neon) —  │  │ (EBS-backed│  │    R2     │ │   or      │       │
│     │  (auth,    │  │  volume on │  │ (uploaded │ │ OpenRouter│       │
│     │ sessions,  │  │  EC2)      │  │   PDFs)   │ │   (LLM)   │       │
│     │ documents) │  │            │  │           │ │           │       │
│     └────────────┘  └────────────┘  └───────────┘ └───────────┘       │
└───────────────────────────────────────────────────────────────────────┘
```

Everything from Nginx down to the Flask/Streamlit containers runs on a single AWS EC2 instance via Docker Compose. ChromaDB's data lives on a separate EBS volume — not the instance's root disk — so it survives the instance itself being replaced. PostgreSQL (Neon), Cloudflare R2, and the LLM provider (OpenRouter) are managed services outside AWS entirely; the EC2 instance is only the compute box that talks to them. Locally, `DATABASE_URL` and the R2 credentials can both be left unset — the app falls back to local SQLite and local disk automatically, so development needs no external accounts.

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
├── docker-compose.dev.yml          # Dev — self-contained (Ollama, debug mode, no restart on crash)
├── docker-compose.prod.yml         # Prod — self-contained (OpenRouter, Neon, R2, memory-limited, restart always)
├── docker-compose.bootstrap.yml    # One-time TLS bootstrap — minimal HTTP-only Nginx + Certbot, no app dependency
├── .env.dev.example                # Dev env template (copy to .env.dev, fill in secrets)
├── .env.prod.example               # Prod env template (copy to .env.prod, fill in secrets)
│
├── nginx/
│   ├── prod.conf                   # Full HTTPS vhost — apex/www split, TLS, security headers, Streamlit + /health proxy
│   └── bootstrap.conf              # HTTP-only vhost used once, to obtain the first Let's Encrypt certificate
│
├── .github/
│   └── workflows/
│       └── deploy.yml                  # GitHub Actions pipeline — lint, test, build+push to GHCR, deploy to EC2
│
├── backend/
│   ├── app.py                      # Flask app factory, blueprint registration, migrate wiring
│   ├── config.py                   # Config + startup validation (DB/storage auto-detection, fail-fast checks)
│   ├── gunicorn.conf.py            # Gunicorn config — preload_app, post_fork DB engine reset, JSON logging
│   ├── llm_provider.py             # LLM factory + 4-model OpenRouter fallback chain
│   ├── logging_config.py           # Structured JSON logging — stdout/stderr authoritative, optional file logging
│   ├── Dockerfile                  # python:3.12-slim, gunicorn, model pre-baked
│   ├── .dockerignore
│   ├── requirements.txt            # Backend-only deps — version-pinned for reproducible ARM64 builds
│   ├── pytest.ini                  # Test config, markers, warning filters
│   ├── wsgi.py                     # Entrypoint for Gunicorn (Docker prod only) + eager model warmup.
│   │
│   ├── extensions/                 # Flask extensions
│   │   ├── db.py                   # SQLAlchemy
│   │   ├── jwt.py                  # JWT
│   │   ├── migrate.py              # Flask-Migrate (Alembic)
│   │   └── limiter.py              # Rate limiter (JWT-keyed, not IP-keyed)
│   │
│   ├── models/                     # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── document.py             # Includes explicit status lifecycle (processing/ready/status)
│   │   └── chat.py                 # ChatSession + Message
│   │
│   ├── migrations/                 # Alembic migration history
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_add_document_deletion_status.py
│   │
│   ├── routes/                     # Flask blueprints
│   │   ├── auth_routes.py          # /register /login /logout
│   │   ├── upload_routes.py        # /upload, /documents (list), /documents/<id> (delete)
│   │   ├── chat_routes.py          # /ask /chat/session /chat/sessions
│   │   └── health_routes.py        # /health (liveness) /health/deep (deps checks)
│   │
│   ├── services/
│   │   ├── rag_service.py          # Full RAG pipeline (ingest, route, retrieve, answer)
│   │   └── storage_service.py      # R2/local storage abstraction — object keys, upload/download/delete
│   │
│   │
│   ├── tests/
│   │   ├── conftest.py             # Shared fixtures
│   │   ├── fixtures/
│   │   │   └── sample.pdf          # 3-page test PDF
│   │   ├── test_unit_config.py     # Tier 1 — config validation
│   │   ├── test_unit_rag.py        # Tier 1 — query router, retry, fallback, threshold, K
│   │   ├── test_unit_storage.py    # Tier 1 — object key construction, local + mocked R2 backends
│   │   ├── test_unit_logging.py    # Tier 1 — JSON formatter, request-context filter correctness
│   │   ├── test_integration_rag.py     # Tier 2 — real Chroma + fixture PDF, mocked LLM
│   │   ├── test_integration_logging_gunicorn.py    # Tier 2 — real Gunicorn subprocess, preload + fork
│   │   └── test_routes.py          # Tier 3 — Flask test client, auth, upload lifecycle, validation
│   │
│   └── storage/                    # Runtime data — gitignored except .gitkeep files
│       │                           # Auto-recreated with .gitkeep on every app startup
│       ├── uploads/                # Local-disk fallback for PDFs (unused when R2 is configured)
│       │   └── .gitkeep
│       ├── vector_db/
│       │    └── chroma_db/         # ChromaDB embeddings (always local)
│       │        └── .gitkeep
│       ├── database/
│       │   ├── rag.db              # SQLite fallback (unused when DATABASE_URL is set)
│       │   └── .gitkeep
│       └── logs/                   # Only used if ENABLE_FILE_LOGGING=true (local dev only)
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
Document row created in Postgres (status=processing) → document.id
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
    │      source, user_id, document_id, chunk_id, page, total_chunks
    │      source, user_id, document_id, chunk_id, page, total_chunks
    │      (document_id is the same Postgres row id, and the same id
    │      used to build the R2/local object key — one identifier
    │      ties all three stores together for consistent lookup/delete)
    │
    ▼
File pushed to storage (R2 or local) under
users/{user_id}/documents/{document_id}/{filename}
    │
    ▼
Document row updated (status=ready, filepath=object key)
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
  compare/concepts/            │
  interview)                   │
       │                   Tiny doc? (≤15 chunks)
       │                   Yes → fetch all chunks
       ▼                   No  → similarity search
  Direct chunk                 │
  fetch (no                Adaptive threshold
  similarity search)       mean + (max-mean)*0.5
       │                   bounded [0.10, 0.40]
       │                       │
       └───────────┬───────────┘
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

A failure at any ingestion step (embedding, storage upload, or the final DB commit) triggers compensating cleanup of whatever already succeeded — no partial document is ever left visible or queryable.

---

## API Endpoints

| Method   | Endpoint          | Auth | Description                                                                                     |
| -------- | ----------------- | ---- | ----------------------------------------------------------------------------------------------- |
| `POST`   | `/register`       | No   | Register new user                                                                               |
| `POST`   | `/login`          | No   | Login, returns JWT token                                                                        |
| `GET`    | `/profile`        | JWT  | Get current user info                                                                           |
| `POST`   | `/upload`         | JWT  | Upload one or more PDFs                                                                         |
| `GET`    | `/documents`      | JWT  | List the current user's fully-ingested (`status=ready`) documents                               |
| `DELETE` | `/documents/<id>` | JWT  | Delete a document — Postgres row, Chroma vectors, and storage object together, safely retryable |
| `POST`   | `/chat/session`   | JWT  | Create new chat session                                                                         |
| `GET`    | `/chat/sessions`  | JWT  | List all sessions (with titles)                                                                 |
| `GET`    | `/chat/<id>`      | JWT  | Get full message history for session                                                            |
| `POST`   | `/ask`            | JWT  | Ask a question — triggers RAG pipeline                                                          |
| `GET`    | `/health`         | No   | Liveness check (Flask + DB)                                                                     |
| `GET`    | `/health/deep`    | No   | Dependency check (Chroma, DB, LLM config, log files sizes)                                      |

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

`DATABASE_URL` and the `R2_*` variables are optional for local dev — leave them unset and the app automatically falls back to local SQLite and local
disk storage, no external accounts needed.

Generate secure keys:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 6. Run database migrations

```
cd backend
flask db upgrade
```

Only needed once against a fresh database (local SQLite included). Re-run after pulling any change that adds a migration under `backend/migrations/versions/`.

### 7. Run the backend

```bash
cd backend
python app.py
# Flask runs at http://127.0.0.1:5000
```

### 8. Run the frontend

```bash
cd frontend
streamlit run app.py
# Streamlit runs at http://localhost:8501
```

---

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable               | Required    | Default                  | Description                                                                                                                 |
| ---------------------- | ----------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`           | ✅          | —                        | Flask session secret                                                                                                        |
| `JWT_SECRET_KEY`       | ✅          | —                        | JWT signing key                                                                                                             |
| `LLM_PROVIDER`         | ✅          | `ollama`                 | `ollama` or `openrouter`                                                                                                    |
| `LLM_MODEL`            | ✅          | `qwen2.5:3b`             | Model ID for the active provider                                                                                            |
| `OPENROUTER_API_KEY`   | Prod only   | —                        | From [openrouter.ai/keys](https://openrouter.ai/keys)                                                                       |
| `DATABASE_URL`         | No          | local SQLite             | Postgres connection string (e.g. Neon); falls back to SQLite when unset                                                     |
| `R2_ACCOUNT_ID`        | No          | —                        | Cloudflare account ID — set together with the other `R2_*` vars to enable R2 storage                                        |
| `R2_ACCESS_KEY_ID`     | No          | —                        | R2 API access key                                                                                                           |
| `R2_SECRET_ACCESS_KEY` | No          | —                        | R2 API secret key                                                                                                           |
| `R2_BUCKET_NAME`       | No          | —                        | R2 bucket name; falls back to local disk storage when unset                                                                 |
| `OLLAMA_HOST`          | Docker only | `http://localhost:11434` | Ollama server URL                                                                                                           |
| `BACKEND_URL`          | Docker/Prod | `http://127.0.0.1:5000`  | Backend URL for frontend                                                                                                    |
| `LLM_TIMEOUT_SECONDS`  | No          | `30`                     | Per-request LLM timeout                                                                                                     |
| `LLM_MAX_RETRIES`      | No          | `2`                      | Retries before fallback triggers                                                                                            |
| `ASK_RATE_LIMIT`       | No          | `10 per minute`          | Rate limit on `/ask` per user                                                                                               |
| `CHUNK_SIZE`           | No          | `1000`                   | PDF chunk size in tokens                                                                                                    |
| `CHUNK_OVERLAP`        | No          | `200`                    | Chunk overlap in tokens                                                                                                     |
| `RETRIEVAL_K`          | No          | `5`                      | Base number of chunks to retrieve                                                                                           |
| `LOG_LEVEL`            | No          | `INFO`                   | Logging level                                                                                                               |
| `ENABLE_FILE_LOGGING`  | No          | `false`                  | Write rotating log files in addition to stdout/stderr — safe only for local single-process dev, never under Gunicorn/Docker |

---

## Usage Guide

### 1. Register and login

Open `http://localhost:8501`, create an account, and login.

### 2. Upload documents

Click **Upload Documents** in the sidebar. Select one or more PDFs. VaultIQ will ingest, chunk, and embed them automatically. Duplicate uploads are detected and skipped. A document only appears in your document list once ingestion, storage, and the database commit have all succeeded.

### 3. Ask questions

Use the welcome screen's suggested questions or type your own:

- **"Summarize the uploaded documents"** — structured document summary
- **"Compare the main topics discussed"** — topic comparison with headings
- **"Explain the important concepts"** — concept list with definitions
- **"Generate interview questions"** — 6 Q&A pairs from document content
- **"What is backpropagation?"** — specific factual lookup
- **"Tell me about the resume.pdf"** — file-specific query (auto-filters to that doc)

### 4. Manage documents

List or delete uploaded documents via `GET /documents` and `DELETE /documents/<id>` — deletion removes the file from storage (R2 or local), its vectors from Chroma, and its database row together.

### 5. Manage sessions

Create multiple chat sessions from the sidebar. Each session has its own history. Click any session to switch to it. Search through session history with the search box.

### 6. View logs

In production (Docker/Gunicorn), logs are structured JSON on stdout/stderr — the authoritative source:

```
docker compose -f docker-compose.prod.yml logs -f backend
```

For local single-subprocess dev, optionally enable rotating log files by setting `ENABLE_FILE_LOGGING=true`:

```bash
tail -f backend/storage/logs/app.log        # All activity (INFO+)
tail -f backend/storage/logs/error.log      # Errors only (WARNING+)
```

Or via the API:

```
GET /health/deep
```

### 7. Reset storage

Delete `backend/storage` to clear local ChromaDB data and any local-disk fallback uploads/SQLite. On next app start, the directory structure and `.gitkeep` files are automatically recreated by `config.py`. When Postgres/R2 are configured, this only affects the local vector store — run `flask db downgrade`/reset your Neon database and empty the R2 bucket separately if you need a full reset.

---

## Testing

VaultIQ has a 3-tier test suite: **149 test cases collected across 8 files** (147 run + 2 deselected by default — see Tier 2 note below). Verified via `pytest tests/ --tb=short`:

```
collected 149 items / 2 deselected / 147 selected
...
147 passed, 2 deselected in 68.90s
```

The raw number of `def test_...` functions in the source is lower (123) — the difference is `@pytest.mark.parametrize`, which collects one test _item_ per parameter row from a single function definition (e.g. one `def test_detect_query_type` generates 24 separate collected cases, one per query-type example).

### Tier 1 — Unit tests (fast, no external dependencies)

```bash
cd backend
pytest tests/test_unit_config.py tests/test_unit_rag.py tests/test_unit_storage.py tests/test_unit_logging.py -v
```

Covers: config validation, query type detection, retry logic, fallback chain, adaptive threshold, dynamic K, source filter helper, provider factory, and retrieval-layer error handling, object-key construction and local/R2 storage-backends (R2 mocked, no network), and the JSON logging formatter + request-context filter (including the regression test proving `request_id`/`user_id` are correctly attached from _any_ module logger, not just root).

### Tier 2 — Integration tests (real Chroma / real Gunicorn, mocked LLM)

```bash
pytest tests/test_integration_rag.py -v
pytest tests/test_integration_logging_gunicorn.py -v
```

`test_integration_rag.py` covers real PDF ingestion, chunk metadata, user isolation, duplicate guard, broad query retrieval, factual retrieval, citation building, LLM failure handling.

`test_integration_logging_gunicorn.py` spins up a real `gunicorn --config gunicorn.conf.py wsgi:app` subprocess (`preload_app=True`, multiple workers) and asserts, from actual process output, that exactly one structured access log line is produced per request with correct `request_id`, and that no log files are created unless `ENABLE_FILE_LOGGING` is explicitly set.

> `test_integration_rag.py` runs by default (needs the full dependency stack — HuggingFace model download — so it's excluded from CI to keep the pipeline fast, but runs locally). `test_integration_logging_gunicorn.py`'s 2 tests are marked `@pytest.mark.gunicorn` and deselected by default _everywhere_ — including local runs — via `pytest.ini`'s `addopts = -m "not gunicorn"`, since spawning a real subprocess is slow and needs `gunicorn` on PATH.
> Run them explicitly: `pytest tests/test_integration_logging_gunicorn.py -m gunicorn -v`.

### Tier 3 — Route tests (Flask test client)

```bash
pytest tests/test_routes.py -v
```

Covers: auth flow, the full upload document lifecycle (validation, duplicate detection, ingest/storage/DB failure paths and their compensating cleanup, document listing and deletion), session ownership enforcement, input validation, health endpoints, rate limiting, and global error handlers (JSON 404/405, and a full round-trip confirming an unexpected exception returns a clean JOSN 500 with real exception message never leaking to client).

### Full suite

```bash
pytest tests/ -v
```

### Test architecture

| Tier            | File                                 | Tests          | External deps                    | Runs in CI    |
| --------------- | ------------------------------------ | -------------- | -------------------------------- | ------------- |
| 1 — Unit        | test_unit_config.py                  | 6              | None                             | ✅            |
| 1 — Unit        | test_unit_rag.py                     | 68             | None                             | ✅            |
| 1 — Unit        | test_unit_storage.py                 | 9              | None (R2 mocked)                 | ✅            |
| 1 — Unit        | test_unit_logging.py                 | 8              | None                             | ✅            |
| 2 — Integration | test_integration_rag.py              | 15             | HuggingFace, ChromaDB            | ❌ local only |
| 2 — Integration | test_integration_logging_gunicorn.py | 2 (deselected) | gunicorn on PATH, full dep stack | ❌ local only |
| 3 — Routes      | test_routes.py                       | 41             | Flask only (mocked services)     | ✅            |
| **Total**       |                                      | **149**        |                                  |               |

---

## Security Considerations

- **JWT authentication** on all protected routes with token expiry
- **Per-user data isolation** — ChromaDB queries are always filtered by `user_id`; one user can never access another's documents or chat history
- **Per-user, per-document storage namespacing** — R2/local object keys are built as `users/{user_id}/documents/{document_id}/{filename}`, so storage paths alone provide no way for one user's request to reach another's files
- **Server-side upload validation** — filename sanitization (path traversal via `../` is stripped, not just cosmetically blocked on the frontend), file-size limits, and PDF magic-byte verification (checks actual file content, not just the claimed extension)
- **Rate limiting** on `/ask` keyed by JWT identity (not IP) — prevents free-tier LLM quota exhaustion by a single user
- **Config validation at startup** — app refuses to boot with missing secrets or invalid provider config rather than failing silently mid-request
- **No secrets in Docker image** — `.env` is in `.dockerignore`; all secrets injected via environment variables at runtime
- **Password hashing** via Werkzeug's `generate_password_hash` / `check_password_hash`
- **Session ownership check** — users can only read their own chat sessions (404 on others)
- **Rotating log files** — bounded at ~150MB total, logs never contain passwords or JWT tokens
- **Global exception handler never leaks internals** — any handled exception, anywhere in the app, returns a generic JSON message to the client; the real exception (with full traceback) is captured only in server-side structured logs, tagged with `request_id`/`user_id` for correlation
- **Consistent JSON error contract** — every response, including 404/405/413/500 and any unexpected failure, is JSON. The client never receives Flask's default HTML error pages or a raw stack trace
- **TLS everywhere in production** — Nginx terminates HTTPS with an auto-renewing Let's Encrypt certificate; HTTP requests are redirected to HTTPS
- **Least-privilege AWS access** — a scoped IAM user (not the AWS root account) provisions and manages resources
- **Key-only SSH** — password authentication is disabled at the OS level on the EC2 instance; the private key is the only way in
- **Defense-in-depth network hardening** — AWS Security Groups restrict inbound traffic at the cloud-provider level (only 22/80/443), with UFW as a second host-level firewall layer and Fail2Ban actively banning IPs after repeated failed SSH attempts

---

## Performance Optimizations

- **Lazy singleton initialization** — embedding model, LLM client, and R2 client are all created on first request, not at import time, so importing any module for testing doesn't trigger model downloads or require credentials
- **Dynamic K retrieval** — `k = min(10, max(3, total_chunks // 30))` scales the retrieval pool with collection size rather than using a fixed value
- **Adaptive relevance threshold** — `threshold = mean + (max - mean) * 0.5` adjusts to each query's score distribution, preventing noise on large docs and over-filtering on small ones
- **Tiny-doc shortcut** — documents with ≤15 chunks bypass similarity search entirely (fetches all chunks directly) since sparse embedding spaces produce unreliable cosine similarities
- **Source-aware filtering** — when a filename is mentioned in the query, ChromaDB is filtered to that document only, eliminating cross-document score pollution
- **Minimal chroma fetches** — metadata-only lookups (filename detection, chunk counting) use `include=["metadatas]` / `include=[]` instead of the default, which otherwise pulls full document text for the entire collection on every single query regardless of relevance
- **Single-query factual retrieval** — `similarity_search_with_scores()` is called once per question and used directly, avoiding a redundant second Chroma query
- **Batched ingestion embedding** — PDF ingestion embeds and stores chunks in configurable batchs (`INGEST_BATCH_SIZE`, default 32) instead of embedding an entire document's chunks in one call, bounding peak memory during ingestion
- **HuggingFace model pre-baked into Docker image** — prevents 30-60 second cold-start delay on first request after deploy
- **Eager model warm-up via `wsgi.py` + gunicorn `preload_app`** — embedding model and LLM client load once in the master process before forking. workers share them via copy-on-write instead of each loading a separate copy. `post_fork` disposes and recreates the SQLAlchemy engine per worker so each gets its own DB connections instead of sharing an inherited, unsafe one
- **Object storage uploads stages locally firsts** — PDFs are validated and ingested from a local temp file before ever being pushed to R2, so a malformed.unparsable PDF never generates unnecessary network traffic
- **Images pre-built for ARM64** — CI builds and pushes `linux/arm64` images to GHCR so the EC2 (Graviton) host pulls a native image instead of building or emulating on every deploy

---

## Observability & Error Handling

VaultIQ went through a dedicated production-stabilization pass covering structured logging, memory optimization, warning suppression, and error handling — the four things that matter most before trusting an app to run unattended.

### Structured logging

- **Every log line is a single JSON object** — `timestamp`, `level`, `logger`, `message`, `request_id`, `user_id`, `module`, `filename`, `line`, plus any caller-supplied structured fields (e.g. `processing_time_ms`, `pdf_filename`, `chunks`) — not free-text, so logs are directly queryable (`jq`, log aggregation tools) instead of needing regex parsing
- **stdout/stderr are the authoritative destination under Docker/Gunicorn** — `RotatingFileHandler` is not safe to share across multiple forked Gunicorn worker processes writing to the same file concurrently (rotation itself isn't process-safe). Docker's own log driver already captures stdout/stderr durably per-container with no such hazard, so file logging is now opt-in only (`ENABLE_FILE_LOGGING=true`), intended for local single-process dev debugging
- **`request_id` and `user_id` are correctly attached from any module** not just root — the request-context filter is attached at the _handler_ level rather than the root logger, because a filter on the root logger silently never runs for records from a child logger (e.g. any ordinary `logging.getLogger(__name__)` call) even though they reach root's handlers via propagation. This was found and fixed with a dedicated regression test
- **One structured completion line per request** — a dedicated `http.access` logger records `endpoint`, `method`, `status`, `processing_time_ms`, and `remote_addr` for every request;Gunicorn's own built-in access log is disabled (`accesslog = None`) Specifically to avoid a second, differently-formatted line duplicating the same request

### Production warning suppression

- **Runtime warning filters, not just test-time ones** — `pytest.ini`'s `filterwarnings` only ever applied during `pytest` runs; the actual deployed app was still emitting the same third-party deprecation noise (langchain-comminity's sunset notice, chromadb's UserWarning, PyJWT's key-length warning, SQLAlchemy's legacy API warning) on every startup and every PDF ingest. The same filters are now applied at runtime.
- **`logging.captureWarnings(True)`** routes any warning _not_ explictly filtered into the same structures JSON logging pipeline instead of leaking raw text to stderr — genuinely new/unexpected warnings stay visible and properly tagged; known noise disappers.

### Error handling

- **Retrieval failures degrade gracefully** — a Chroma open failure, index corruption, or an embedding-computation error while embedding the user's question is caught and returns a clean, generic answer instead of propagating as an unhandled exception
- **Upload failures compensate, never orphan** — a failure at any stage of ingestion (embedding, R2/local upload, or the final DB commit) triggers independent, individually-logged cleanup of whatever already succeeded (Chroma vectors, storage object, DB row); if cleanup itself can't fully complete, the document is marked `status="failed"` rather than silently left inconsistent
- **Global exception handler** — `@app.errorhandler(Exception)` catches anything not already handled by a more specific path (upload, embedding, vector DB, and LLM failures each have their own targeted handling); logs the real exception with full traceback server-side only, returns a short, safe, generic JSON message to the client
- **Consistent JSON error response** for 404 (unknown route), 405 (wrong method), 413 (upload too large), and any unexpected 500 — this is a JSON-only API and every response, success or failure

---

## Known Limitations

- **Local Ollama generation time on long-form answers (dev environment only)** `qwen2.5:3b` running on CPU via Ollama generates output proportionally to requested length, not just input/context size. Query types that explicitly ask for long, multi-part output — `interview` (6 full Q&A pairs), or a `factual`/`summarize` question phrased as "explain each type in detailed with examples" — can exceed even a generous gunicorn worker timeout (300s in dev) on typical development hardware. Shorter or more direct questions complete comfortably within 1-3 minutes.
  - This is a **dev-only** limitation. Production uses OpenRouter's hosted inference (`google/gemma-4-31b-it:free` and its fallback chain), which is dramatically faster than local CPU-bound Ollama and does not exhibit this behaviour.
  - No code changes are needed to work around this for local testing — prefer more direct/scoped questions when testing against Ollama, or expect longer waits on deliberately verbose prompts.
- **ChromaDB stays on local disk** — a deliberate choice at current scale rather than an oversight; Postgres and file storage were the two layers that actually needed to survive redeploys and container recreation. Revisit only if vector data volume outgrows what a single VPS disk can hold.
- **No stale-document reconciliation job yet** — a hard process crash (OOM kill, `SIGKILL`) between ingestion steps can leave a document stuck in `status="processing"`. The explicit status column makes a cleanup job for this straightforward to add; it doesn't exist yet.
- **Production runs on a 2GB RAM instance (`t4g.small`, AWS free tier)** — shared across Nginx, Streamlit, and Flask/Gunicorn (with the embedding model loaded in memory). Backend/frontend container memory limits (768MB/384MB) and Gunicorn's `preload_app` + batched ingestion embedding are deliberate choices to fit this budget, not defaults; a memory-heavier workload (many concurrent large-PDF ingestions, for instance) would need a bigger instance rather than further tuning.

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
2. Test (pytest)        ~30s   — Tier 1 + Tier 3, mocked LLM, no API keys/DB/R2 needed
    │ passes
    │
    ├── PR / feature branch -> STOP (no deploy)
    │
    └── push to main only
            │
            ▼
        3. Build ARM64 images (backend + frontend), push to GHCR
           tagged by commit SHA
            │
            ▼
        4. Deploy to AWS EC2 (manual approval gate)
           SSH in, pull new images, run `flask db upgrade`,
           bring the stack up, health-check the live domain
```

### Production Deployment (AWS)

Production runs on a single AWS EC2 instance (`t4g.small`, ARM/Graviton, Ubuntu 24.04 LTS) via Docker Compose, behind Nginx with an auto-renewing Let's Encrypt TLS certificate. ChromaDB's data lives on a dedicated EBS volume — not the instance's root disk — so it survives the instance itself being replaced. PostgreSQL (Neon), file storage (R2), and the LLM provider (OpenRouter) are managed services outside AWS; the EC2 instance is only the compute box that talks to them.

**Domain:** [https://vault-iq.in](https://vault-iq.in), registered via GoDaddy, pointed at the instance's Elastic IP. `www.vault-iq.in` redirects to the canonical apex domain.

**Deployment flow:** every push to `main` that passes lint + tests triggers a build of ARM64 Docker images, pushed to GitHub Container Registry (GHCR) tagged by commit SHA. A manually-approved deploy job then SSHes into the EC2 instance, pulls the new images, runs the Alembic migration (`flask db upgrade`, explicitly pointed at `app.py` via `FLASK_APP` — not `wsgi.py`, which additionally runs embedding-model and LLM warmup at import time and would turn a schema-only migration into a slower, more failure-prone step), and restarts the stack — followed by an automated health check against the live domain.

### TLS Bootstrap (one-time, before the first deploy)

Certbot's HTTP-01 challenge needs a webserver answering on port 80 _before_ any certificate exists — but `nginx/prod.conf` requires a certificate to even start. `docker-compose.bootstrap.yml` breaks that circular dependency:

```
docker-compose.bootstrap.yml
    │
    ▼
Minimal HTTP-only Nginx (nginx/bootstrap.conf)
    — no dependency on backend/frontend, serves only
      /.well-known/acme-challenge/
    │
    ▼
Certbot — obtains the first certificate for
    vault-iq.in and www.vault-iq.in
    │
    ▼
Bootstrap stack torn down
    │
    ▼
docker-compose.prod.yml brought up — nginx/prod.conf
    now finds a real certificate at
    /etc/letsencrypt/live/vault-iq.in/
```

Both the bootstrap and production Nginx share the same `certbot-etc` and `certbot-webroot` Docker volumes, so the certificate obtained during bootstrap is exactly what production TLS serves. Renewal (a separate periodic Certbot run, not part of this bootstrap flow) reloads Nginx via a `--deploy-hook` rather than relying on the certificate files changing on disk alone.

**Containers on the EC2 instance:** `nginx` (TLS termination, reverse proxy, security headers, upload size limit, `/health` passthrough), `frontend` (Streamlit), and `backend` (Flask/Gunicorn). There is no separate Chroma container — it's an embedded library writing to the EBS-mounted volume.

### Running with Docker (dev and prod environments)

VaultIQ has two compose files with different models, matching how each environment is actually used:

- **docker-compose.dev.yml** — fully self-contained, builds images locally (`--build`).Meant to run on a laptop.
- **docker-compose.prod.yml** — pulls pre-built, tested images from GHCR by tag (`IMAGE_TAG=sha-<commit>`). Never builds locally in production — the image that gets deployed is the exact one that passed CI, not a fresh local build that might differ.

```
docker-compose.dev.yml     dev — Ollama, DEBUG logging, local SQLite/disk, no restart on crash, builds locally
docker-compose.prod.yml    prod — OpenRouter, Neon Postgres, Cloudflare R2, INFO logging, restart always, pulls from GHCR
.env.dev                   dev secrets (only SECRET_KEY + JWT_SECRET_KEY needed)
.env.prod                ← prod secrets (add OPENROUTER_API_KEY, DATABASE_URL, R2_* vars)
```

**Setup — first time only:**

```bash
cp .env.dev.example  .env.dev    # fill in SECRET_KEY + JWT_SECRET_KEY
cp .env.prod.example .env.prod   # fill in SECRET_KEY + JWT_SECRET_KEY + OPENROUTER_API_KEY + DATABASE_URL + R2_* vars
```

**Development (Ollama, local SQLite/disk — no external accounts needed):**

```bash
# First time: pull the Ollama model
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d ollama
docker exec vaultiq_ollama ollama pull qwen2.5:3b

# Start
docker compose -f docker-compose.dev.yml --env-file .env.dev up --build

# Stop
docker compose -f docker-compose.dev.yml down
```

**Production simulation (OpenRouter + Neon + R2 — tests prod config locally before deploying):**

Since `docker-compose.prod.yml` pulls by tag rather than building, simulating it locally means building and tagging the images yourself first:

```bash

# Start
docker compose -f docker-compose.prod.yml --env-file .env.prod up --build

# Stop
docker compose -f docker-compose.prod.yml down
```

**Key differences per environment:**

| Setting         | Dev                                          | Prod                                                                                                                             |
| --------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| LLM             | Ollama `qwen2.5:3b`                          | OpenRouter `gemma-4-31b-it:free`                                                                                                 |
| Database        | Local SQLite                                 | Neon PostgreSQL                                                                                                                  |
| File storage    | Local disk                                   | Cloudflare R2                                                                                                                    |
| Ollama service  | ✅ Included                                  | ❌ Not needed (API call)                                                                                                         |
| LOG_LEVEL       | DEBUG                                        | INFO                                                                                                                             |
| LLM timeout     | 120s (local CPU inference is slow)           | 30s (API calls are fast)                                                                                                         |
| Retries         | 1                                            | 2                                                                                                                                |
| Rate limit      | 100/min (no quota to protect)                | 10/min (protects OpenRouter free tier)                                                                                           |
| Restart policy  | `no` (stay stopped on crash to inspect logs) | `unless-stopped` (auto-recover)                                                                                                  |
| Memory limit    | None                                         | Backend 768MB / frontend 384MB (sized for the EC2 `t4g.small` instance's 2GB total, leaving headroom for Nginx/OS/Docker daemon) |
| Volume name     | `vaultiq_backend_storage_dev`                | `vaultiq_backend_storage_prod`                                                                                                   |
| Container names | `vaultiq_backend_dev`                        | `vaultiq_backend_prod`                                                                                                           |

Dev uses a named Docker volume so local ChromaDB/fallback data persists across container recreation on a laptop. Prod uses an EBS bind mount instead — a named Docker volume would only survive _container_ recreation, but an EBS volume survives the whole _EC2 instance_ being replaced, which is the actual failure mode this needs to protect against.

---

## Project Status

| Phase                                                     | Status      |
| --------------------------------------------------------- | ----------- |
| Backend (Flask API + RAG pipeline)                        | ✅ Complete |
| Frontend (Streamlit)                                      | ✅ Complete |
| Test suite (149 tests, 3 tiers)                           | ✅ Complete |
| CI/CD (GitHub Actions)                                    | ✅ Complete |
| Docker (backend + frontend + compose)                     | ✅ Complete |
| Database migration (SQLite → Neon Postgres)               | ✅ Complete |
| File storage migration (local disk → Cloudflare R2)       | ✅ Complete |
| Document lifecycle + deletion endpoints                   | ✅ Complete |
| Structured stdout/stderr logging                          | ✅ Complete |
| `docker-compose.prod.yml`: pulls by tag from GHCR         | ✅ Complete |
| AWS deployment guide (EC2/EBS/Nginx/TLS/monitoring)       | 🔜 Planned  |
| Nginx (TLS-only) + Certbot bootstrap in repo              | 🔜 Planned  |
| CI/CD: lint → test → ARM64 build → push GHCR → deploy EC2 | 🔜 Planned  |
| Stale-document reconciliation job                         | 🔜 Planned  |

---

## Future Improvements

### Near-term (backend already supports these — UI/pipeline work remaining)

- **Document management page** — a dedicated UI page listing all uploaded documents with a delete action per document. The backend already exposes both endpoints (`GET /documents`, `DELETE /documents/<id>`, see [API Endpoints](#api-endpoints)); this is purely a Streamlit page + sidebar link, no new backend work needed
- **Multi-format document ingestion** — extend the upload pipeline beyond PDF to accept Word documents (`.docx`), plain text (`.txt`), and Markdown (`.md`). Requires format-specific loaders feeding into the same chunking/embedding pipeline (`PyPDFLoader` swapped for `Docx2txtLoader`/`TextLoader`/`UnstructuredMarkdownLoader` depending on file type), plus extending the upload route's magic-byte/extension validation to the new formats

### Other Improvements

- **Stale-document reconciliation job** — a background task to find and clean up documents stuck in `status="processing"` after a hard crash (OOM kill, `SIGKILL`) between ingestion steps
- **Docker log retention** — explicit `max-size`/`max-file` rotation on the Docker log driver itself, plus optional shipping to an external log aggregator (e.g. Grafana Loki, Better Stack) for logs that need to survive a container being recreated
- **Streaming LLM responses** — pipe token stream from OpenRouter to Streamlit for real-time output
- **Re-ranking** — add a cross-encoder re-ranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) after MMR retrieval for higher precision
- **Multi-modal support** — extract and embed images, tables, and diagrams from PDFs (not just text)
- **Conversation-aware retrieval** — include recent chat history in the retrieval query for multi-turn follow-up questions
- **Document collections** — let users organise documents into named collections and query within a collection
- **Export** — download chat history as PDF or Markdown
- **Automated cert renewal monitoring** — alerting if Let's Encrypt auto-renewal ever fails, rather than discovering it when the cert expires

## Acknowledgements

- [LangChain](https://langchain.com) — RAG pipeline framework
- [ChromaDB](https://trychroma.com) — vector store
- [Sentence Transformers](https://sbert.net) — `all-MiniLM-L6-v2` embedding model
- [OpenRouter](https://openrouter.ai) — unified LLM API gateway
- [Ollama](https://ollama.ai) — local LLM inference
- [Neon](https://neon.tech) — managed serverless PostgreSQL
- [Cloudflare R2](https://cloudflare.com/r2) — S3-compatible object storage
- [Streamlit](https://streamlit.io) — frontend framework

---

## License

MIT License — see [LICENSE](https://github.com/sreesyam064/vaultiq/blob/main/LICENSE) for details.

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
