import requests
import os

# Double-slash URLs
# Original: BASE_URL = "http://127.0.0.1:5000/"
# Every endpoint called as f"{BASE_URL}/register" → "http://127.0.0.1:5000//register"
# Flask ignores the double slash locally, but it can fail on deployed reverse
# proxies (nginx, Render's routing layer). Remove the trailing slash from BASE_URL.
# BASE_URL is configurable via env var so the same image
# works in all environments without rebuilding:
#   Local (no Docker):  http://127.0.0.1:5000   (default)
#   Docker Compose:     http://backend:5000     (set via BACKEND_URL env var)
#   Production Render:  https://your-api.onrender.com  (set via BACKEND_URL env var)
BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000").rstrip("/")

# HTTP request timeouts
# requests has NO default timeout, so without timeout= every HTTP request can
# block indefinitely if the backend hangs or becomes unreachable.
#
# Different operations have different expected runtimes, so each uses a timeout
# appropriate for the work being performed:
#   SHORT_TIMEOUT — pure DB reads/writes (auth, sessions, profile) - always fast                    
#   UPLOAD_TIMEOUT — PDF parsing + local embedding computation - CPU-bound,
#                    no external API call, but can take a while for large docs
#   ASK_TIMEOUT — LLM call itself. Sized to comfortably exceed the backend's own 
#                 worst-case gunicorn worker timeout (see GUNICORN_TIMEOUT in gunicorn.conf.py / docker-compose)
#                 so a legitimately slow-but-successful fallback-chain response isn't cut off client-side before 
#                 the server itself would have given up. Still finite - the whole
#                 point is the UI can no longer hang indefinitely.
SHORT_TIMEOUT  = 15
UPLOAD_TIMEOUT = 120
ASK_TIMEOUT    = 420


def _request(method, url, timeout, **kwargs):
    """
    This wrapper around requests.request() that turns two most common failure modes
    (timeout, can't reach server at all) into clear, user-facing messages instead of 
    raw exception text like "HTTPConnectionPool(...): Max retries exceeds..." or a bare
    ConnectTimeout traceback.
    """
    try:
        return requests.request(method, url, timeout=timeout, **kwargs)
    
    except requests.exceptions.Timeout:
        raise Exception(
            f"The server took too long to respond (waited {timeout}s). "
            "Please try again in a moment."
        )    

    except requests.exceptions.ConnectionError:
        raise Exception(
            f"Could not reach the VaultIQ backend. "
            "Please check your connection and try again."
        )  




# Authentication

def register_user(username, email, password):
    payload = {
        "username": username,
        "email": email,
        "password": password
    }
    response = _request("POST", f"{BASE_URL}/register", timeout=SHORT_TIMEOUT, json=payload)
    response.raise_for_status()
    return response.json()


def login_user(email, password):
    payload = {
        "email": email,
        "password": password
    }
    response = _request("POST", f"{BASE_URL}/login", timeout=SHORT_TIMEOUT, json=payload)
    response.raise_for_status()
    return response.json()


# Chat Session APIs
def create_session(token):
    headers = {"Authorization": f"Bearer {token}"}
    response = _request("POST", f"{BASE_URL}/chat/session", timeout=SHORT_TIMEOUT, headers=headers)
    response.raise_for_status()
    return response.json()


def get_sessions(token):
    headers = {"Authorization": f"Bearer {token}"}
    response = _request("GET", f"{BASE_URL}/chat/sessions", timeout=SHORT_TIMEOUT, headers=headers)
    response.raise_for_status()
    return response.json()


def load_chat(token, session_id):
    headers = {"Authorization": f"Bearer {token}"}
    response = _request("GET", f"{BASE_URL}/chat/{session_id}", timeout=SHORT_TIMEOUT, headers=headers)
    response.raise_for_status()
    return response.json()


# Ask Question
def ask_question(token, session_id, question):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "session_id": session_id,
        "question": question
    }
    response = _request(
        "POST", f"{BASE_URL}/ask", timeout=ASK_TIMEOUT, 
        headers=headers,json=payload
    )
    response.raise_for_status()
    return response.json()


# Upload Documents
def upload_documents(token, uploaded_files):
    headers = {"Authorization": f"Bearer {token}"}
    files = [
        ("file", (file.name, file, "application/pdf")) 
        for file in uploaded_files
    ]
    response = _request(
        "POST", f"{BASE_URL}/upload", timeout=UPLOAD_TIMEOUT, 
        headers=headers, files=files
    )
    if response.status_code in (200, 409, 500, 413, 400):
        return response.json()
    
    response.raise_for_status()
    return response.json()