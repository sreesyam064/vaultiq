# Backend Dockerfile — VaultIQ Flask API

FROM python:3.12-slim


# Prevents Python from writing .pyc files (not needed in containers)
# and ensures stdout/stderr are unbuffered (logs appear in real time)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app


# System dependencies
# gcc + g++ : required to build chromadb's native extensions
# curl      : used by Docker health check below
# --no-install-recommends: skip suggested packages (saves ~40MB)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
# Copy requirements first — Docker caches this layer separately.
# If only app code changes (not requirements), this layer is reused and 
# pip install is skipped entirely an rebuilds. Fast rebuilds matter 
# when iterating locally and in CI
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# HuggingFace embedding model pre-download
# WHY: sentence-transformers downloads all-MiniLM-L6-v2 (~90MB) on first use.
# If we dont pre-download it here, the first request after deploy takes 30-60 seconds
# to respond (model download) and Render's health check may time out, causing a false 
# deploy failure.
# Baking it into image means model is always available at startup.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Force offline model loading at runtime
# WHY: sentense-transformers / huggingface_club still makes a network call to check for an updated
#   etag/manifest EVERY TIME model is instantiated — even though we just pre-downloaded weights above.
#   that network round trip is separate from any app-level timeout (LLM_TIMEOUT_SECONDS, gunicorn --timeout)
#   because it happens inside huggingface_club's own connection
#   logic — raising your own timeouts does nothing to it. This was actual cause of first request latency.
#   HF_HUB_OFFLINE=1 forces pure local-cache loading with zero network calls.
#   Safe because weights are already baked into image above.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Application code
COPY . .

# Storage dirs
# Creates storage structure inside img
# in production, these are OVERRIDEN by a persistent disk mount at /app/storage — so data survives
# redeploys.
# In local Docker, these dirs exist but data is lost on container removal
# unless you mount a volume (see docker-compose.yml)
RUN mkdir -p storage/uploads storage/vector_db/chroma_db storage/database storage/logs

# Port
EXPOSE 5000

# Health check
# DOcker itself pools this to mark the container healthy/unhealthy
#   --interval: check every 30s
#   --timeout: fail if no response in 10s
#   --retries: mark unhealthy after 3 consecutive failures
#   --start-period: give app 60s to start before health check begin
#   Now 90s because wsgi.py eagerly loads embedding model and constructs LLM client at container startup
#   instead of deferring that cost to first request. Startup is slightly slow;
#   first real user request is now fast instead of timing out.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD curl -f http://localhost:5000/health || exit 1

# Entrypoint
# WHY gunicorn instead of `python app.py`
#   Flask's built-in dev server is single-threaded and not safe for production.
#   gunicorn is a production WSGI server that handles concurrent requests,
#   graceful restarts, and worker process management.



# WHY wsgi:app instead of app:app:
#   wsgi.py eagerly warms embedding model, LLM client, and DB tables ONCE before
#   gunicorn forks workers. app.py alone stays cheap to import so test suite can 
#   import it directly without triggering real model downloads or network calls.

# All worker count, timeout, and logging settings now live in gunicorn.conf.py
# (--config flag below)  rather than CLI flags — this is what makes `preload_app` and `post_fork` 
# DB-reset hook possible.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]