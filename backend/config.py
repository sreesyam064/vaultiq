import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Environment
# Explicit, not inferred. Auto-detecting "production" from mere presence of DATABASE_URL/R2_* vars
# is exactly how a misconfigured prod deploy silently falls back to SQLite/local disk instead of failing.
# APP_ENV must be set explicitly; "development" is safee default for local work, 
# "production" turns on strict checks below.
APP_ENV = os.getenv("APP_ENV", "development").lower().strip()
if APP_ENV not in ("development", "production"):
    raise RuntimeError(f"APP_ENV must be 'development' or 'production', got '{APP_ENV}'")

BASE_DIR=Path(__file__).resolve().parent

STORAGE_DIR         = BASE_DIR / "storage"
UPLOAD_FOLDER       = STORAGE_DIR / "uploads"
VECTOR_DB_PATH      = STORAGE_DIR / "vector_db"
CHROMA_DB_PATH      = VECTOR_DB_PATH / "chroma_db"
SQLITE_DB_DIR_PATH  = STORAGE_DIR / "database"
SQLITE_DB_PATH      = SQLITE_DB_DIR_PATH / "rag.db"
LOG_DIR             = STORAGE_DIR / "logs"



def _ensure_dir(path):
    """
    Create a directory and restore its .gitkeep file if missing.

    This ensures empty storage directories remain tracked by Git after a
    storage reset, preventing missing directory errors on fresh clones
    or application startup.
    """
    os.makedirs(path, exist_ok=True)
    gitkeep = Path(path) / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

_ensure_dir(UPLOAD_FOLDER)
_ensure_dir(CHROMA_DB_PATH)
_ensure_dir(SQLITE_DB_DIR_PATH)
_ensure_dir(LOG_DIR)

UPLOAD_FOLDER   = str(UPLOAD_FOLDER)
CHROMA_DB_PATH  = str(CHROMA_DB_PATH)
SQLITE_DB_PATH  = str(SQLITE_DB_PATH)

# File Storage (uploaded PDFs)
# Same auto-detect pattern as DATABASE_URL:if R2 credentials are present — use Cloudflare R2.
# Otherwise fallback to local disk to local disk (UPLOAD_FOLDER) — keep local dev / docker-compose.dev.yml 
# working with zero extra config.
R2_ACCOUNT_ID        = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID     = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME       = os.getenv("R2_BUCKET_NAME")
# R2's S3-compatible endpoint is always this shape — derived from acc id, never needs to be set manually.
R2_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None

_r2_fullt_configured = all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME])
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "r2" if _r2_fullt_configured else "local").lower().strip()

# Core Secrets
SECRET_KEY      = os.getenv("SECRET_KEY")
JWT_SECRET_KEY  = os.getenv("JWT_SECRET_KEY")

# Database
# DATABASE_URL is standard 12-factor env var most Postges hosts (Neon) inject automatically.
# If it's set, use it. Otherwise fallback to local file SQLite

# Neon hand out URLs with legacy "postgres://" schema. SQLAlchemy 1.4+ requires "postgresql://"
# (or driver-specific variant like "postgresql_psycopg://"), so normalize itt.
_raw_database_url = os.getenv("DATABASE_URL")

def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

if _raw_database_url:
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(_raw_database_url)    
    _USING_POSTGRES = True
else:
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{SQLITE_DB_PATH}"
    _USING_POSTGRES = False
    
# SQLALCHEMY_DATABASE_URI         = f"sqlite:///{SQLITE_DB_PATH}"
SQLALCHEMY_TRACK_MODIFICATIONS  = False

# Neon(serverless/managed postgresql) sits behind a pooler and will silently close idle connection.
# without pool_pre_ping, first query after any idle period raises "SSL connection has been closed unexpectedly"
# instead of transparently reconnecting. pool_recycle forces SQLAlchemy to refresh connections before Neon's own idle
# timeout kicks in. These options are meaningless for SQLite, so they are only applied when actually running against Postgresql.
if _USING_POSTGRES:
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {"sslmode": "require"},
    }
else:
    SQLALCHEMY_ENGINE_OPTIONS = {}

# LLM Provider Configurations
# Two wnvironments, two values:
#   Development:    LLM_PROVIDER=ollama     LLM_MODEL=qwen2.5:3b
#   Production :    LLM_PROVIDER=openrouter LLM_MODEL=google/gemma-4-31b-it:free
#
# OpenRouter is a single API gateway to all free-tier LLMs under one key.
# Production uses a fallback chain (in llm_provider.py):
#   Primary:   google/gemma-4-31b-it:free   (256K context, strong instruction following)
#   Backup:    openai/gpt-oss-120b:free     (highest capacity free model)
#   Fallback:  openai/gpt-oss-20b:free      (fast MoE, reliable)
#   Emergency: openrouter/free              (auto-picks any available free model)
# If LLM_MODEL is rate-limited or offline, the fallback chain tries the next
# model automatically — the app stays alive even when one model goes down.
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "ollama").lower().strip()
LLM_MODEL       = os.getenv("LLM_MODEL", "qwen2.5:3b")

# Only one key needed — OPENROUTER_API_KEY forproduction.
# Ollama is keyless (runs locally).
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")

_PROVIDER_API_KEYS = {
    "ollama": None,
    "openrouter": OPENROUTER_API_KEY,
}
# LLM call tuning
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_MAX_RETRIES     = int(os.getenv("LLM_MAX_RETRIES", "2"))

# RAG pipeline
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
CHUNK_SIZE      = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP   = int(os.getenv("CHUNK_OVERLAP", "200"))
RETRIEVAL_K     = int(os.getenv("RETRIEVAL_K", "5"))

# Process embeddings in batches instead of all at once to keep usage low and 
# avoid OOM crashes when ingesting large PDFs.
INGEST_BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "32"))

# Rate limiting
# Applied to /ask only. Free-tier OpenRouter has per-model daily limits —
# this prevents one user from burning the quota for everyone else.
ASK_RATE_LIMIT  = os.getenv("ASK_RATE_LIMIT", "10 per minute")

# rate limiting for /login and /register
# to avoid unlimited brute-force / credential-stuffing attempts.
AUTH_RATE_LIMIT = os.getenv("AUTH_RATE_LIMIT", "5 per minute")

# Upload limits
# MAX_UPLOAD_SIZE_MB caps single file's size. Also used to set flask's 
# MAX_CONTENT_LENGTH (total request body cap) in app.py, so a single file 
# request cant smuggle a huge payload past per-file check by splitting it across
# many small-looking multipart fields.
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Max no.of files accepted in single /upload request. 
MAX_FILES_PER_UPLOAD = int(os.getenv("MAX_FILES_PER_UPLOAD", "10"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# File logging is disabled by default because RotatingFileHandler is not
# process-safe across multiple Gunicorn workers. Docker stdout/stderr is the
# production logging destination. Enable only for local single-process debugging.
ENABLE_FILE_LOGGING = os.getenv("ENABLE_FILE_LOGGING", "false").strip().lower() == "true"


def validate_config():
    """
    Fail fast at startup instead of failing deep inside a request.
    
    Without this, a missing SECRET_KEY or a misconfigured LLM_PROVIDER
    would only surface the first time a user hits an affected route —
    example: JWT signing breaks silently, or ask_question() crashes after
    a slow ingest. In a deployed app that's a confiusing 500 error with
    no clear cause in the logs. Failing at boot means broken config shows
    up immediately in the deploy logs, before traffic ever hits the app.
    """
    errors = []
    
    if not SECRET_KEY:
        errors.append("SECRET_KEY is not set")
    if not JWT_SECRET_KEY:
        errors.append("JWT_SECRET_KEY is not set")
        
    # Development is allowed to fallback to SQLite/locla disk (that fallsback is what makes local dev work with zero config).
    # Production is NOT — if APP_ENV=production and either fallback is in effect, means a required env var is missing, 
    # and app must refuse to boot rather than quietly start writing "production" data to container's ephemeral local disk.    
    if APP_ENV == "production":
        if not _USING_POSTGRES:
            errors.append(
                "APP_ENV=production but DATABASE_URL is not set — refusing to "
                "fall back to local SQLite in production. Set DATABASE_URL to "
                "your Neon connection string."
            )
        if  STORAGE_BACKEND != "r2":
            errors.append(
                "APP_ENV=production but STORAGE_BACKEND resolved to 'local' — "
                "refusing to fall back to local dick storage in production" 
                "(container disk is ephemeral). Set R2_ACCOUNT_ID, "
                "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME." 
            )
        
        if _USING_POSTGRES:
            try:
                import psycopg # noqa: F401
            except ImportError:
                errors.append(
                    "DATABASE_URL points at Postgres but the 'psycopg[binary]' "
                    "driver is not installed. Run pip install \"psycopg[binary]\""
                )
        
        if STORAGE_BACKEND == "r2":
            missing_r2 = [
                name for name, val in [
                    ("R2_ACCOUNT_ID", R2_ACCOUNT_ID),
                    ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
                    ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY),
                    ("R2_BUCKET_NAME", R2_BUCKET_NAME),
                ] if not val
            ]
            if missing_r2:
                errors.append(f"STORAGE_BACKEND=r2 but missing: {', '.join(missing_r2)}")
            try:
                import boto3    # noqa: F401
            except ImportError:
                errors.append(
                    "STORAGE_BACKEND-r2 but 'boto3' is not installed. "
                    "Run: pip install boto3"
                )
        elif STORAGE_BACKEND != "local":
            errors.append(f"STORAGE_BACKEND must be 'r2' or 'local', got '{STORAGE_BACKEND}'")
        
    valid_providers = set(_PROVIDER_API_KEYS.keys())
    if LLM_PROVIDER not in valid_providers:
        errors.append(
            f"LLM_PROVIDER='{LLM_PROVIDER}' is invalid. "
            f"Expected one of: {sorted(valid_providers)}"
        )
       
    elif LLM_PROVIDER == "openrouter" and not OPENROUTER_API_KEY:
        errors.append("LLM_PROVIDER='openrouter' requires OPENROUTER_API_KEY to be set")
     
    if errors:
        message = "Configuration error(s) detected at startup:\n" + "\n".join(f"  -{e}" for e in errors)
        logger.error(message)
        # Fail loudly and stop the process — do not let the app boot half-configured.
        print(message, file=sys.stderr)
        sys.exit(1)
        
    logger.info(f"Config validated. LLM_PROVIDER='{LLM_PROVIDER}', LLM_MODEL='{LLM_MODEL}'")
    
def get_llm_api_key() -> str:
    # Return the API key for whichever provider is currently active.
    return _PROVIDER_API_KEYS.get(LLM_PROVIDER)
