import requests

BASE_URL = "http://127.0.0.1:5000"

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