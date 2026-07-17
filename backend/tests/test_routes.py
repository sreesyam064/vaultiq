"""
Tier 3 — Route TEsts: Auth, Upload, Chat, Health via Flask Test Client
======================================================================
These tests hit Flask routes via test client. The service layer 
(ask_question, ingest_pdf) is mocked — we're testing routing, auth enforcement,
validation, status codes, and response shapes.
No Chroma, no LLM, no real PDFs needed here

whats tested:
    /register       - happy path, duplicate username/email, missing fields
    /login          - happy path, wrong password, missing fields
    /profile        - auth required, correct user data returned
    /upload         - auth required, no file, duplicate file guard
    /ask            - auth required, validation, missing session, no docs guard
    /chat/*         - session creation, ownership, history
    /health         - Flask alive, DB reachable
    /health/deep    - Chroma path + LLM config reported
"""

import os
import sys
import io
import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
    

# Auth routes

class TestAuthRegister:
    
    def test_register_success(self, client, db_session):
        resp = client.post("/register", json={
            "username": "newuser",
            "email":    "new@example.com",
            "password": "password123",
        })
        assert resp.status_code == 201
        assert resp.get_json()["message"] == "User registered successfully"
        
    def test_register_missing_fields(self, client, db_session):
        resp = client.post("/register", json={"username": "onlyname"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()
        
    def test_register_duplicate_username(self, client, db_session):
        payload = { "username": "dupuser", "email": "a@a.com", "password": "pass"}
        client.post("/register", json=payload)
        payload["email"] = "b@b.com"
        resp = client.post("/register", json=payload)
        assert resp.status_code == 409
        assert "Username already exists" in resp.get_json()["error"]
        
    def test_register_duplicate_email(self, client, db_session):
        client.post("/register", json={"username": "user1", "email": "same@x.com", "password": "pass"})
        resp = client.post("/register", json={"username": "user2", "email": "same@x.com", "password": "pass"})
        assert resp.status_code == 409
        assert "Email already exists" in resp.get_json()["error"]
        

class TestAuthLogin:
    
    def test_login_success(self, client, db_session):
        client.post("/register", json={"username": "loginuser", "email": "login@x.com", "password": "mypass"})
        resp = client.post("/login", json={"email": "login@x.com", "password": "mypass"})
        data = resp.get_json()
        assert resp.status_code == 200
        assert "token" in data
        assert data["user"]["email"] == "login@x.com"
        
    def test_login_wrong_password(self, client, db_session):
        client.post("/register", json={"username": "passuser", "email": "pass@x.com", "password": "correct"})
        resp = client.post("/login", json={"email": "pass@x.com", "password": "wrong"})
        assert resp.status_code == 401
        assert "Invalid" in resp.get_json()["error"]
        
    def test_login_nonexixtent_email(self, client, db_session):
        resp = client.post("/login", json={"email": "nobody@x.com", "password": "pass"})
        assert resp.status_code == 401
        
    def test_login_missing_fields(self, client, db_session):
        resp = client.post("/login", json={"email": "only@email.com"})
        assert resp.status_code == 400
        
        
class TestAuthProfile:
    
    def test_profile_requires_auth(self, client, db_session):
        # Hitting /profile without a token must  return 401/422.
        resp = client.get("/profile")
        assert  resp.status_code in (401, 422)
        
    def test_profile_returns_user_data(selff, client, db_session, auth_headers):
        resp = client.get("/profile", headers=auth_headers)
        data = resp.get_json()
        assert resp.status_code == 200
        assert "username" in data
        assert "email" in data
        

# Upload routes
class TestUploadRoute:
    
    def test_upload_requires_auth(self, client, db_session):
        resp = client.post("/upload")
        assert resp.status_code in (401, 422)
        
    def test_upload_no_file_returns_400(self, client, db_session, auth_headers):
        resp = client.post("/upload", headers=auth_headers, data={})
        assert resp.status_code == 400
        assert "error" in resp.get_json()
        
    def test_upload_non_matching_key_returns_400(self, client, db_session, auth_headers):
        # Sending a file under wrong form key should return 400.
        data = {"wrong_key": (io.BytesIO(b"%PDF-1.4 test"), "test.pdf")}
        resp = client.post(
            "/upload", headers=auth_headers,
            data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 400
        
    def test_upload_duplicate_file_returns_409(self, client, db_session, auth_headers, monkeypatch):
        # Uploading same filename twice should return 409 on second attempt
        
        # Mock ingest_pdf so we don't need a real PDF or Chroma in this tier
        monkeypatch.setattr("routes.upload_routes.ingest_pdf", lambda path, uid: 5)
        
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        data = {"file": (io.BytesIO(pdf_bytes), "report.pdf")}
        
        # First upload
        client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "report.pdf")},
            content_type="multipart/form-data"
        )        
        # Second upload — same filename
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "report.pdf")},
            content_type="multipart/form-data"
        )
        data = resp.get_json()
        assert resp.status_code == 409
        assert "skipped" in data
        
    def test_upload_ingest_failure_does_not_create_orphaned_record(self, client, db_session, auth_headers, monkeypatch):
        """
        if ingest_pdf() raises(e.g. worker crash, OOM, corrupt PDF), SQL Document row must NOT be created.
        Previously SQL commit happened before ingest_pdf() ran, so a failure here would leave a permanent orphaned 
        record — file would be struck forever, blocked by duplicate check on every future upload attempt, with
        zero actual data in ChromaDB.
        """
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid: (_ for _ in ()).throw(RuntimeError("simulated ingest crash")),
        )
        
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "crashy.pdf")},
            content_type="multipart/form-data"
        )
        
        data = resp.get_json()
        
        # Genuine failure -> 500, reported as a distinct "errors" entry
        assert resp.status_code == 500
        assert "errors" in data
        assert data["errors"][0]["file"] == "crashy.pdf"
        assert "uploaded" not in data
        assert "skipped" not in data
        
        # Criitical assertion: no SQL Document record exists for this file.
        # If old buggy ordering were still in place, this would find a row and file would
        # be perminantly stuck.
        with client.application.app_context():
            from models import Document
            existing = Document.query.filter_by(filename="crashy.pdf").first()
            assert existing is None, (
                "Document row should NOT exist after a failed ingest — "
                "this is exactly the orphaned-record bug this fix addresses"
            )
            
    def test_upload_retry_succeeds_after_ingest_failure(self, client, db_session, auth_headers, monkeypatch):
        """
        After a failed upload (ingest_pdf raised), retrying SAME filename must succeed — not be blocked
        by a stale duplicate-check, since no SQL row was created on failyure.
        """
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        # First attempt: ingest_pdf fails
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid: (_ for _ in ()).throw(RuntimeError("simulated crash")),
        )
        first = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "retry.pdf")},
            content_type="multipart/form-data"
        )
        assert first.status_code == 500

        # Second attempt: ingest_pdf now succeeds (simulates the transient
        # failure — e.g. OOM under load — not recurring on retry)
        monkeypatch.setattr("routes.upload_routes.ingest_pdf", lambda path, uid: 5)
        second = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "retry.pdf")},
            content_type="multipart/form-data"
        )
        data = second.get_json()

        # Must succeed as a fresh upload, NOT be rejected as a duplicate
        assert second.status_code == 200
        assert "uploaded" in data
        assert data["uploaded"][0]["file"] == "retry.pdf"
        assert "skipped" not in data           
        
# Chat routes

class TestChatRoutes:
    
    def test_create_session_requires_auth(self, client, db_session):
        resp = client.post("/chat/session")
        assert resp.status_code in (401, 422)
        
    def test_create_session_success(self, client, db_session, auth_headers):
        resp = client.post("/chat/session", headers=auth_headers)
        assert resp.status_code == 201
        assert "session_id" in resp.get_json()
        
    def test_get_chat_history_empty(self, client, db_session, auth_headers):
        # A new session should return an empty message list.
        session_resp = client.post("/chat/session", headers=auth_headers)
        session_id = session_resp.get_json()["session_id"]
            
        resp = client.get(f"/chat/{session_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json() == []
            
    def test_chat_wrong_session_returns_404(self, client, db_session, auth_headers):
        """Requesting a session that doesnt exist (or belongs to another user)
        must return 404, not a 500 or leaked data."""
        resp = client.get("/chat/99999", headers=auth_headers)
        assert resp.status_code == 404
            
    def test_ask_requires_auth(self, client, db_session):
        resp = client.post("/ask", json={"session_id": 1, "question": "hi"})
        assert resp.status_code in (401, 422)
            
    def test_ask_missing_fields_returns_400(self, client, db_session, auth_headers):
        resp = client.post("/ask", headers=auth_headers, json={"session_id": 1})
        assert "error" in resp.get_json()
            
    def test_ask_no_documents_return_400(self, client, db_session, monkeypatch):
        """
        Asking a question when no PDFs have been uploaded must return 400
        with a clear message, not crash into the RAG pipeline.
        Uses a fresh user (nodocs@x.com) who has never uploaded anytrhing.
        """
        monkeypatch.setattr(
            "routes.chat_routes.ask_question",
            lambda q, uid: {"answer": "Should not reach here", "sources": []}
        )
        # Register +login a fresh user with no documents
        client.post("/register", json={
            "username": "nodocuser", "email": "nodocs@x.com", "password": "pass123"
        })
        login = client.post("/login", json={"email": "nodocs@x.com", "password": "pass123"})
        fresh_headers = {"Authorization": f"Bearer {login.get_json()['token']}"}
            
        session_resp = client.post("/chat/session", headers=fresh_headers)
        session_id = session_resp.get_json()["session_id"]
            
        resp = client.post("/ask", headers=fresh_headers, json={
            "session_id": session_id,
            "question": "What is this about?"
        })
        assert resp.status_code == 400
        assert "No documents" in resp.get_json()["error"]
            
    def test_ask_full_flow(self, client, db_session, auth_headers, monkeypatch):
        """
        Full /ask happy path with mocked service layer.
        Verifies: session ownership check, message saved, answer returned.
        """
        monkeypatch.setattr(
            "routes.chat_routes.ask_question",
            lambda q, uid: {"answer": "Mocked answer", "sources": ["sample.pdf (Page 1)"]}
        )
            
        # Add a document record so the "no docs" guard passes
        from models import Document
        from extensions import db
        from flask import current_app
            
        with client.application.app_context():
            from flask_jwt_extended import decode_token
            token = auth_headers["Authorization"].split(" ")[1]
            user_id = int(decode_token(token)["sub"])
            doc = Document(user_id=user_id, filename="sample.pdf", filepath="/fake/path.pdf")
            db.session.add(doc)
            db.session.commit()
                
        session_resp = client.post("/chat/session", headers=auth_headers)
        session_id = session_resp.get_json()["session_id"]
            
        resp = client.post("/ask", headers=auth_headers, json={
            "session_id": session_id,
            "question": "What is backpropagation?"
        })
        data = resp.get_json()
            
        assert resp.status_code == 200
        assert data["answer"] == "Mocked answer"
        assert data["sources"] == ["sample.pdf (Page 1)"]
            
    def test_ask_auto_titles_session(self, client, db_session, auth_headers, monkeypatch):
        # The first question in a session should auto-populate session.title.
        monkeypatch.setattr(
            "routes.chat_routes.ask_question",
            lambda q, uid: {"answer": "Answer", "sources": []}
        )
        
        with client.application.app_context():
            from flask_jwt_extended import decode_token
            from models import Document
            from extensions import db
            token   = auth_headers["Authorization"].split(" ")[1]
            user_id = int(decode_token(token)["sub"])
            doc     = Document(user_id=user_id, filename="sample2.pdf", filepath="/fake/2.pdf")
            db.session.add(doc)
            db.session.commit()
        
        session_resp = client.post("/chat/session", headers=auth_headers)
        session_id   = session_resp.get_json()["session_id"]
 
        question = "What is the transformer architecture?"
        client.post("/ask", headers=auth_headers, json={
            "session_id": session_id,
            "question":   question
        })
        
        with client.application.app_context():
            from models import ChatSession
            session = db.session.get(ChatSession, session_id)
            assert session.title is not None
            assert session.title == question[:40]
            

# Health routes

class TestHealthRoutes:
    def test_health_returns_200(self, client, db_session):
        """Basic health check must always return 200 when Flask + DB are up."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["checks"]["flask"] == "ok"
        assert data["checks"]["database"] == "ok"
 
    def test_health_deep_returns_200(self, client, db_session):
        """/health/deep must return 200 and report LLM config fields."""
        resp = client.get("/health/deep")
        data = resp.get_json()
        # May be ok or degraded depending on whether Chroma path exists in test env
        assert resp.status_code in (200, 503)
        assert "checks" in data
        assert "llm_provider" in data["checks"]
        assert "llm_model" in data["checks"]
 
    def test_health_no_auth_needed(self, client):
        """Health endpoints must be publicly accessible — no JWT required."""
        resp = client.get("/health")
        assert resp.status_code != 401
        assert resp.status_code != 422
        
class TestGlobalErrorHandling:
    # Tests for global error handlers in app.py.
    def test_unknown_route_returns_json_404(self, client, db_session):
        # This API always returns JSON, including for routes that dont exist insted of Flask's default 404 (HTML page).
        resp = client.get("/this/route/does/not/exist")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data is not None, "404 response must be JSON, not HTML"
        assert "error" in data
        
    def test_wrong_method_returns_json_405(self, client, db_session):
        resp = client.get("/register")
        assert resp.status_code == 405
        data = resp.get_json()
        assert data is not None, "405 response must be JSON, not HTML"
        assert "error" in data
        
    def test_unexpected_exception_returns_clean_json_500(self, client, db_session, auth_headers, monkeypatch):
        # Ensure the global exception handler returns a clean JSON 500 for any
        # unexpected error instead of Flask's default HTML error page.
        monkeypatch.setattr(
            "routes.chat_routes.ask_question",
            lambda q, uid: (_ for _ in ()).throw(RuntimeError("simulated totally unexpected crash")),
        )
        
        from models import Document
        from extensions import db
        from flask_jwt_extended import decode_token
        
        with client.application.app_context():
            token = auth_headers["Authorization"].split(" ")[1]
            user_id = int(decode_token(token)["sub"])
            # Use a unique filename to avoid the (user_id, filename)
            # unique constraint when other tests create sample.pdf.
            doc = Document(user_id=user_id, filename="crash-test-doc.pdf", filepath="/fake/path.pdf")
            db.session.add(doc)
            db.session.commit()
            
        session_resp = client.post("/chat/session", headers=auth_headers)
        session_id = session_resp.get_json()["session_id"]
        
        resp = client.post("/ask", headers=auth_headers, json={
            "session_id": session_id,
            "question": "this will crash",
        })
        
        assert resp.status_code == 500
        data = resp.get_json()
        assert data is not None, "500 response must be JSON, not HTML"
        assert "error" in data
        # real exception msg must never leak to client
        assert "simulated totally unexpected crash" not in data["error"]
        assert "RuntimeError" not in data["error"]
        
        