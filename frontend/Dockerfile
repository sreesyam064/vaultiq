# Frontend Dockerfile

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies
# curl required for HEALTHCHECK cmd below
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Application code include .streamlit/config.toml (Streamlit config)
COPY . .

# Port
EXPOSE 8501

# Health check
#   Streamlit exposes /_stcore/health as a built-in in liveness endpoint.
#   --start-period 30s: give streamlit time to boot before checks begin.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entrypoints
CMD ["streamlit", "run", "app.py", \
    "--server.headless=true", \
    "--server.port=8501", \
    "--server.address=0.0.0.0"]