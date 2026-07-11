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

# Authentication

def register_user(username, email, password):
    payload = {
        "username": username,
        "email": email,
        "password": password
    }
    response = requests.post(
        f"{BASE_URL}/register",
        json=payload
    )
    response.raise_for_status()
    return response.json()


def login_user(email, password):
    payload = {
        "email": email,
        "password": password
    }
    response = requests.post(
        f"{BASE_URL}/login",
        json=payload
    )
    response.raise_for_status()
    return response.json()


# Chat Session APIs
def create_session(token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{BASE_URL}/chat/session",
        headers=headers
    )
    response.raise_for_status()
    return response.json()


def get_sessions(token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/chat/sessions",
        headers=headers
    )
    response.raise_for_status()
    return response.json()


def load_chat(token, session_id):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{BASE_URL}/chat/{session_id}",
        headers=headers
    )
    response.raise_for_status()
    return response.json()


# Ask Question
def ask_question(token, session_id, question):
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "session_id": session_id,
        "question": question
    }
    response = requests.post(
        f"{BASE_URL}/ask",
        headers=headers,
        json=payload
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
    response = requests.post(
        f"{BASE_URL}/upload",
        headers=headers,
        files=files
    )
    response.raise_for_status()
    return response.json()