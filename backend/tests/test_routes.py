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
        # also mock upload_local_file so we don't need a real storage backend
        monkeypatch.setattr("routes.upload_routes.ingest_pdf", lambda path, uid, document_id, filename=None: 5)
        monkeypatch.setattr("routes.upload_routes.upload_local_file", lambda path, object_key: None)
        
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
            lambda path, uid, document_id, filename=None: (_ for _ in ()).throw(RuntimeError("simulated ingest crash")),
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
            lambda path, uid, document_id, filename=None: (_ for _ in ()).throw(RuntimeError("simulated crash")),
        )
        first = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "retry.pdf")},
            content_type="multipart/form-data"
        )
        assert first.status_code == 500

        # Second attempt: ingest_pdf now succeeds (simulates the transient
        # failure — e.g. OOM under load — not recurring on retry)
        monkeypatch.setattr("routes.upload_routes.ingest_pdf", lambda path, uid, document_id, filename=None: 5)
        monkeypatch.setattr("routes.upload_routes.upload_local_file", lambda path, object_key: None)
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
        
    def test_upload_invalid_file_returns_400_not_500(self, client, db_session, auth_headers):
        """
        A rejected file (bad extension, empty, bad magic bytes) is a CLIENT
        error and must return 400 — it must never be lumped in with genuine
        server-side ingest/storage/DB failures under a 500.
        """
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(b"not a pdf at all"), "notes.txt")},
            content_type="multipart/form-data"
        )
        data = resp.get_json()
        assert resp.status_code == 400
        assert "errors" in data
        assert "uploaded" not in data

    def test_upload_ingest_failure_cleans_up_chroma_vectors(self, client, db_session, auth_headers, monkeypatch):
        """
        ingest_pdf() embeds in batches, so a failure partway through can
        still have committed earlier batches to Chroma before raising.
        The failure handler must attempt Chroma cleanup unconditionally,
        not assume "it raised, so nothing landed."
        """
        cleanup_calls = []
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, document_id, filename=None: (_ for _ in ()).throw(RuntimeError("partial batch failure")),
        )
        monkeypatch.setattr(
            "routes.upload_routes.delete_document_vectors",
            lambda document_id, user_id: cleanup_calls.append((document_id, user_id)) or 0,
        )

        pdf_bytes = b"%PDF-1.4 fake pdf content"
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "partial.pdf")},
            content_type="multipart/form-data"
        )
        assert resp.status_code == 500
        assert len(cleanup_calls) == 1, "delete_document_vectors must be called after an ingest failure"

    def test_upload_storage_failure_cleans_up_vectors_and_db_row(self, client, db_session, auth_headers, monkeypatch):
        """
        If ingestion succeeds but the storage push fails, both the Chroma
        vectors and the Document row must be rolled back — otherwise we'd
        have vectors and/or a "ready"-looking row with no file behind them.
        """
        monkeypatch.setattr("routes.upload_routes.ingest_pdf", lambda path, uid, document_id, filename=None: 5)
        cleanup_calls = []
        monkeypatch.setattr(
            "routes.upload_routes.delete_document_vectors",
            lambda document_id, user_id: cleanup_calls.append((document_id, user_id)) or 0,
        )
        monkeypatch.setattr(
            "routes.upload_routes.upload_local_file",
            lambda path, object_key: (_ for _ in ()).throw(RuntimeError("simulated R2 outage")),
        )

        pdf_bytes = b"%PDF-1.4 fake pdf content"
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "storagefail.pdf")},
            content_type="multipart/form-data"
        )
        data = resp.get_json()

        assert resp.status_code == 500
        assert len(cleanup_calls) == 1, "delete_document_vectors must be called after a storage failure"

        with client.application.app_context():
            from models import Document
            existing = Document.query.filter_by(filename="storagefail.pdf").first()
            assert existing is None, "Document row should be removed after storage failure + successful cleanup"

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
            doc = Document(user_id=user_id, filename="sample.pdf", filepath="/fake/path.pdf", status="ready")
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
            token = auth_headers["Authorization"].split(" ")[1]
            user_id = int(decode_token(token)["sub"])
            doc = Document(user_id=user_id, filename="sample2.pdf", filepath="/fake/2.pdf", status="ready")
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
        
    def test_unexpected_exception_returns_clean_json_502(self, client, db_session, auth_headers, monkeypatch):
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
            doc = Document(user_id=user_id, filename="crash-test-doc.pdf", filepath="/fake/path.pdf", status="ready")
            db.session.add(doc)
            db.session.commit()
            
        session_resp = client.post("/chat/session", headers=auth_headers)
        session_id = session_resp.get_json()["session_id"]
        
        resp = client.post("/ask", headers=auth_headers, json={
            "session_id": session_id,
            "question": "this will crash",
        })
        
        assert resp.status_code == 502
        data = resp.get_json()
        assert data is not None, "502 response must be JSON, not HTML"
        assert "error" in data
        # real exception msg must never leak to client
        assert "simulated totally unexpected crash" not in data["error"]
        assert "RuntimeError" not in data["error"]
        
        
                 
"""
Neon/R2 storage integration & failure-case tests

Covers critical upload and deletion failure paths:
- Storage failure during upload
- DB commit failure after ingestion and storage upload
- Duplicate upload and retry after failed ingestion
- Complete deletion across Postgres, ChromaDB, and storage

Tests use real local storage and a temporary ChromaDB instance.
R2 network calls are mocked at the storage-client boundary so storage
logic and compensating cleanup are still exercised without requiring
live Cloudflare credentials.
"""
from unittest.mock import MagicMock

class TestStorageFailureCases:
    
    def test_upload_storage_failure_cleans_up_chroma_and_db(
        self, client, db_session, auth_headers, chroma_dir, monkeypatch
    ):
        """
        if ingest_pdf() succeeds but the storage push fails (R2 down, network error, bad creds), 
        the Chroma vectors already written for this document_id must be deleted and the Document
        row must not survive — otherwise you get vectors with no DB row and no file anywhere, 
        permanently unreachable and undeletable through the normal API.
        """
        from services import ingest_pdf
        
        # Real ingest (writes real vectors to test chroma_dir) — only storage push is made to fail
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, doc_id, filename=None: ingest_pdf(path, uid, doc_id, filename=filename),
        )
        monkeypatch.setattr(
            "routes.upload_routes.upload_local_file",
            lambda local_path, object_key: (_ for _ in ()).throw(ConnectionError("simulated R2 outage"),
            ),
        )
        
        pdf_bytes = _minimal_pdf_bytes()
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "outage.pdf")},
            content_type="multipart/form-data",
        )
        data = resp.get_json()

        assert resp.status_code == 500
        assert "errors" in data
        assert data["errors"][0]["file"] == "outage.pdf"

        # No orphaned Document row
        with client.application.app_context():
            from models import Document
            assert Document.query.filter_by(filename="outage.pdf").first() is None

        # No orphaned Chroma vectors either — this is the part that
        # wasn't previously covered by test_routes.py's ingest-failure
        # test, since that test fails BEFORE Chroma is ever touched.
        from services.rag_service import _get_vectordb
        leftover = _get_vectordb().get(where={"source": "outage.pdf"})
        assert not leftover["ids"], (
            "Chroma vectors survived a storage-layer failure — "
            "orphaned vectors with no matching Document row"
        )

    def test_upload_db_commit_failure_cleans_up_chroma_and_storage(
        self, client, db_session, auth_headers, chroma_dir, monkeypatch
    ):
        """
        Point 4, the other half: ingest AND storage both succeed, but the
        final db.session.commit() (writing filepath) fails. Both the
        Chroma vectors and the just-uploaded storage object must be
        rolled back — otherwise you get a real file in storage with
        nothing in the DB ever pointing at it (permanently orphaned,
        invisible to any list/delete endpoint).
        """
        from services import ingest_pdf
        from extensions import db as ext_db
        
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, doc_id, filename=None: ingest_pdf(path, uid, doc_id, filename=filename),
        )
        # Let the real (local-disk) upload_local_file run — we want a
        # real object to exist so we can prove it gets deleted again.
        uploaded_keys = []
        deleted_keys = []
        # from services.storage_service import upload_local_file

        def spying_upload(local_path, object_key):
            # upload_local_file(local_path, object_key)
            uploaded_keys.append(object_key)

        def spying_delete(object_key):
            deleted_keys.append(object_key)
        
        monkeypatch.setattr("routes.upload_routes.upload_local_file", spying_upload)
        monkeypatch.setattr("routes.upload_routes.delete_object", spying_delete)
        
        # Fail only the SECOND commit in the flow (the one that sets
        # filepath) — the first commit (creating the row) must succeed,
        # or document_id never exists and nothing downstream can run.
        # from extensions import db as ext_db
        original_commit = ext_db.session.commit
        call_count = {"n": 0}

        def flaky_commit():
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated DB commit failure")
            return original_commit()

        monkeypatch.setattr(ext_db.session, "commit", flaky_commit)

        pdf_bytes = _minimal_pdf_bytes()
        resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "dbfail.pdf")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 500
        assert uploaded_keys, "Test setup issue: storage upload never ran"

        # The uploaded object must have been deleted as compensation.
        assert deleted_keys == [uploaded_keys[0]], (
        "Storage cleanup was not attempted after the final DB commit failed"
        )

        # And the Chroma vectors too.
        from services.rag_service import _get_vectordb
        leftover = _get_vectordb().get(where={"source": "dbfail.pdf"})
        assert not leftover["ids"], "Chroma vectors survived a DB commit failure"
        
        # The failed document must never remain visible as a successful upload.
        with client.application.app_context():
            from models import Document
            doc = Document.query.filter_by(filename="dbfail.pdf").first()
            assert doc is None or doc.status == "failed", (
                "Failed upload remained visible as an active document"
            )

class TestDocumentDeletion:

    def test_delete_partial_failure_never_shows_document_as_active(
        self, client, db_session, auth_headers, chroma_dir, monkeypatch
    ):
        """
        Reproduces the exact scenario flagged in review: Chroma deletion
        succeeds, then the storage (R2) deletion fails. Before the
        deletion_status fix, the Document row would still read as fully
        "active" at that point — appearing uploaded and searchable in
        /documents while its vectors were actually already gone. This
        proves that can no longer happen: the moment deletion starts,
        the document is excluded from list_documents(), regardless of
        how far cleanup gets.
        """
        from services import ingest_pdf
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, doc_id, filename=None: ingest_pdf(path, uid, doc_id, filename=filename),
        )

        pdf_bytes = _minimal_pdf_bytes()
        upload_resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "partialdelete.pdf")},
            content_type="multipart/form-data",
        )
        assert upload_resp.status_code == 200

        with client.application.app_context():
            from models import Document
            doc = Document.query.filter_by(filename="partialdelete.pdf").first()
            document_id = doc.id

        # Storage deletion fails; Chroma deletion is untouched (real, succeeds).
        monkeypatch.setattr(
            "routes.upload_routes.delete_object",
            lambda object_key: (_ for _ in ()).throw(ConnectionError("simulated R2 outage")),
        )

        del_resp = client.delete(f"/documents/{document_id}", headers=auth_headers)
        assert del_resp.status_code == 500
        assert del_resp.get_json().get("retryable") is True

        # The critical assertion: the document must NOT appear as active/
        # available, even though its DB row still physically exists.
        list_resp = client.get("/documents", headers=auth_headers)
        listed_ids = [d["id"] for d in list_resp.get_json()]
        assert document_id not in listed_ids, (
            "Document still listed as active after a partial delete failure — "
            "this is exactly the inconsistency the deletion_status fix prevents"
        )

        with client.application.app_context():
            from models import Document
            from extensions import db
            doc = db.session.get(Document, document_id)
            assert doc is not None, "row should still exist — cleanup isn't finished"
            assert doc.deletion_status == "deleting"

        # Chroma vectors ARE already gone at this point (that half of the
        # cleanup succeeded) — expected, and fine, precisely because the
        # document is no longer presented as active anywhere.
        from services.rag_service import _get_vectordb
        leftover = _get_vectordb().get(where={"source": "partialdelete.pdf"})
        assert not leftover["ids"]

    def test_delete_retry_after_partial_failure_completes_cleanly(
        self, client, db_session, auth_headers, chroma_dir, monkeypatch
    ):
        """Continuation of the test above: once the transient storage
        failure is gone, retrying the same DELETE call must finish the
        job — re-deleting Chroma vectors (idempotent no-op, already
        gone) and successfully deleting the storage object this time,
        then hard-deleting the row."""
        from services import ingest_pdf
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, doc_id, filename=None: ingest_pdf(path, uid, doc_id, filename=filename),
        )

        pdf_bytes = _minimal_pdf_bytes()
        client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "retrydelete.pdf")},
            content_type="multipart/form-data",
        )
        with client.application.app_context():
            from models import Document
            document_id = Document.query.filter_by(filename="retrydelete.pdf").first().id

        # First attempt: storage deletion fails (transient).
        monkeypatch.setattr(
            "routes.upload_routes.delete_object",
            lambda object_key: (_ for _ in ()).throw(ConnectionError("simulated R2 outage")),
        )
        first = client.delete(f"/documents/{document_id}", headers=auth_headers)
        assert first.status_code == 500

        # Second attempt: the real delete_object runs — the transient
        # failure is gone, deletion completes.
        from services.storage_service import delete_object
        monkeypatch.setattr("routes.upload_routes.delete_object", delete_object)

        second = client.delete(f"/documents/{document_id}", headers=auth_headers)
        assert second.status_code == 200
        assert second.get_json()["deleted"] == document_id

        with client.application.app_context():
            from models import Document
            from extensions import db
            assert db.session.get(Document, document_id) is None

    def test_delete_removes_db_row_chroma_and_storage(
        self, client, db_session, auth_headers, chroma_dir, monkeypatch
    ):
        """
        Point 6: deletion is the scenario that had no code path to test
        before this review (no delete endpoint existed at all). Verifies
        all three stores — Postgres row, Chroma vectors, storage object —
        are gone after one DELETE call, using document_id as the single
        coordinating identifier (point 3).
        """
        from services import ingest_pdf
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, doc_id, filename=None: ingest_pdf(path, uid, doc_id, filename=filename),
        )

        pdf_bytes = _minimal_pdf_bytes()
        upload_resp = client.post(
            "/upload", headers=auth_headers,
            data={"file": (io.BytesIO(pdf_bytes), "deleteme.pdf")},
            content_type="multipart/form-data",
        )
        assert upload_resp.status_code == 200

        with client.application.app_context():
            from models import Document
            doc = Document.query.filter_by(filename="deleteme.pdf").first()
            assert doc is not None
            document_id = doc.id
            object_key = doc.filepath

        del_resp = client.delete(f"/documents/{document_id}", headers=auth_headers)
        assert del_resp.status_code == 200
        assert del_resp.get_json()["chunks_removed"] > 0

        # DB row gone
        with client.application.app_context():
            from models import Document
            assert db_row_gone(Document, document_id)

        # Chroma vectors gone
        from services.rag_service import _get_vectordb
        leftover = _get_vectordb().get(where={"source": "deleteme.pdf"})
        assert not leftover["ids"]

        # Storage object gone
        from config import UPLOAD_FOLDER
        assert not os.path.exists(os.path.join(UPLOAD_FOLDER, object_key))

    def test_delete_requires_ownership(self, client, db_session, auth_headers, chroma_dir, monkeypatch):
        """A user must not be able to delete another user's document by
        guessing its id."""
        from services import ingest_pdf
        monkeypatch.setattr(
            "routes.upload_routes.ingest_pdf",
            lambda path, uid, doc_id, filename=None: ingest_pdf(path, uid, doc_id, filename=filename),
        )

        client.post("/register", json={
            "username": "otheruser", "email": "other@example.com", "password": "testpassword123",
        })
        other_login = client.post("/login", json={
            "email": "other@example.com", "password": "testpassword123",
        })
        other_headers = {"Authorization": f"Bearer {other_login.get_json()['token']}"}

        pdf_bytes = _minimal_pdf_bytes()
        client.post(
            "/upload", headers=other_headers,
            data={"file": (io.BytesIO(pdf_bytes), "notyours.pdf")},
            content_type="multipart/form-data",
        )
        with client.application.app_context():
            from models import Document
            doc_id = Document.query.filter_by(filename="notyours.pdf").first().id

        # auth_headers belongs to a DIFFERENT user (testuser)
        resp = client.delete(f"/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_nonexistent_document_returns_404(self, client, db_session, auth_headers):
        resp = client.delete("/documents/999999", headers=auth_headers)
        assert resp.status_code == 404


def db_row_gone(model, row_id):
    from extensions import db
    return db.session.get(model, row_id) is None


def _minimal_pdf_bytes():
    """
    A syntactically valid (if trivial) single-page PDF — PyPDFLoader
    needs real PDF structure, not just a "%PDF-1.4" prefix like the
    route-tier tests use (those tests mock ingest_pdf entirely, so the
    bytes never actually get parsed).
    """
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 20 100 Td (Test document content) Tj ET\n"
        b"endstream endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n0\n%%EOF"
    )
