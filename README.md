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

The project was built as a portfolio piece demonstrating end-to-end ML system design — from PDF ingestion and embedding to intelligent query routing, multi-user isolation, JWT authentication, rate limiting, structured logging, a 112-test pytest suite and GitHub Actions CI/CD.

---

## Key Features

- **PDF ingestion pipeline** — upload multiple PDFs, automatically chunked and embedded into a persistent vector store with per-user isolation
- **Intelligent query routing** — detects query intent and applies the optimal retrieval strategy for each type:
  - `summarize` → direct chunk fetch for document overview
  - `compare` → broad multi-chunk fetch for topic comparison
  - `concepts` → concept-focused retrieval
  - `interview` → structured Q&A generation
  - `factual` → MMR similarity search with adaptive threshold
- **Adaptive retrieval** — dynamic K scaling based on collection size, adaptive relevance threshold that adjusts to document density, tiny-doc shortcut for short documents
- **Source-aware filtering** — detects filename references in queries and restricts retrieval to that document
- **Multi-session chat** — create, switch, and search named chat sessions with full history
- **Page-level citations** — every answer includes source filename and page number
- **LLM provider abstraction** — Ollama locally, OpenRouter (free tier) in production
- **4-model fallback chain** — if primary model is rate-limited, automatically tries backup → fallback → emergency
- **Production hardening** — JWT auth, rate limiting, config validation at startup, retry/timeout on all LLM calls, rotating file logging, `/health` and `/health/deep` endpoints
- **112-test pytest suite** — unit, integration, and route tests across 3 tiers

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
│
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions pipeline
│
├── backend/
│   ├── app.py                      # Flask app factory, blueprint registration
│   ├── config.py                   # Config + startup validation
│   ├── llm_provider.py             # LLM factory + 4-model OpenRouter fallback chain
│   ├── logging_config.py           # Rotating file logging setup
│   ├── pytest.ini                  # Test config + warning filters
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
git clone https://github.com/YOUR_USERNAME/vaultiq.git
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

VaultIQ has a 3-tier test suite with **112 tests**.

### Tier 1 — Unit tests (fast, no external dependencies)

```bash
cd backend
pytest tests/test_unit_config.py tests/test_unit_rag.py -v
```

Covers: config validation, query type detection, retry logic, fallback chain, adaptive threshold, dynamic K, source filter helper, provider factory.

### Tier 2 — Integration tests (real Chroma, mocked LLM)

```bash
pytest tests/test_integration_rag.py -v
```

Covers: real PDF ingestion, chunk metadata, user isolation, duplicate guard, broad query retrieval, factual retrieval, citation building, LLM failure handling.
Covers: auth flow (register/login/profile), duplicate upload detection, session ownership enforcement, input validation, rate limiting, health endpoints.

> Requires HuggingFace embedding model download (~90MB on first run). Run locally before pushing — excluded from CI to keep pipeline fast.

### Tier 3 — Route tests (Flask test client)

```bash
pytest tests/test_routes.py -v
```

Covers: auth flow, duplicate upload detection, session ownership enforcement, input validation, health endpoints, rate limiting.

### Full suite

```bash
pytest tests/ -v
```

### Test architecture

| Tier            | File                    | Tests   | External deps                | Runs in CI    |
| --------------- | ----------------------- | ------- | ---------------------------- | ------------- |
| 1 — Unit        | test_unit_config.py     | 6       | None                         | ✅            |
| 1 — Unit        | test_unit_rag.py        | 64      | None                         | ✅            |
| 2 — Integration | test_integration_rag.py | 15      | HuggingFace, ChromaDB        | ❌ local only |
| 3 — Routes      | test_routes.py          | 27      | Flask only (mocked services) | ✅            |
| **Total**       |                         | **112** |                              |               |

---

## Security Considerations

- **JWT authentication** on all protected routes with token expiry
- **Per-user data isolation** — ChromaDB queries are always filtered by `user_id`; one user can never access another's documents or chat history
- **Rate limiting** on `/ask` keyed by JWT identity (not IP) — prevents free-tier LLM quota exhaustion by a single user
- **Config validation at startup** — app refuses to boot with missing secrets or invalid provider config rather than failing silently mid-request
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
- **MMR retrieval** — Maximal Marginal Relevance diversifies retrieved chunks so the LLM receives a broader document cross-section rather than near-identical paragraphs

---

## Project Status

| Phase                                 | Status      |
| ------------------------------------- | ----------- |
| Backend (Flask API + RAG pipeline)    | ✅ Complete |
| Frontend (Streamlit)                  | ✅ Complete |
| Test suite (112 tests, 3 tiers)       | ✅ Complete |
| CI/CD (GitHub Actions)                | ✅ Complete |
| Docker (backend + frontend + compose) | 🔜 Planned  |
| Deployment (Render)                   | 🔜 Planned  |
| Persistent storage upgrade            | 🔜 Planned  |

---

## Future Improvements

- **Streaming LLM responses** — pipe token stream from OpenRouter to Streamlit for real-time output
- **Re-ranking** — add a cross-encoder re-ranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) after MMR retrieval for higher precision
- **Multi-modal support** — extract and embed images, tables, and diagrams from PDFs (not just text)
- **Conversation-aware retrieval** — include recent chat history in the retrieval query for multi-turn follow-up questions
- **Document collections** — let users organise documents into named collections and query within a collection
- **Export** — download chat history as PDF or Markdown

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
