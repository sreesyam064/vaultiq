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
#   (embedding model load + DB init takes ~20-30s on first boot)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD curl -f http://localhost:5000/health || exit 1

# Entrypoint
# WHY gunicorn instead of `python app.py`
#   Flask's built-in dev server is single-threaded and not safe for production.
#   gunicorn is a production WSGI server that handles concurrent requests,
#   graceful restarts, and worker process management.

# -w 2 : 2 worker processes
#   WHY 2 and not more: each worker loads embedding model (~500MB RAM).
#   Render's free tier has 512MB RAM. 2 workers = safer than 4.
#   Formula for workers is usually (2 * CPU cores) + 1, but RAM is the 
#   binding constraint here on free-tier hosting.

# --timeout 120 : worker killed if a request takes > 120s
#   WHY 120: LLM calls (even fast ones via OpenRouter) can take 10-30s.
#   The default gunicorn timeout of 30s would kill the worker mid-LLM-call.

# --bind 0.0.0.0:5000 : listen on all interfaces inside container (not just 127.0.0.1)
#   so Docker's port mapping can reach it

CMD ["sh", "-c", "\
    python init_db.py && \
    exec gunicorn \
    --workers 1 \
    --timeout 300 \
    --bind 0.0.0.0:5000 \
    --access-logfile - \
    --error-logfile - \
    app:app"]