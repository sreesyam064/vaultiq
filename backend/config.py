import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

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

# Core Secrets
SECRET_KEY      = os.getenv("SECRET_KEY")
JWT_SECRET_KEY  = os.getenv("JWT_SECRET_KEY")

SQLALCHEMY_DATABASE_URI         = f"sqlite:///{SQLITE_DB_PATH}"
SQLALCHEMY_TRACK_MODIFICATIONS  = False

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
