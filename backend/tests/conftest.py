"""
conftest.py — shared pytest fixtures for entire test suite
==========================================================
This file is automatically loaded by pytest before any test runs.
Fixtures defined here are available to ALL test files wiithout importing.

whats defined here:
    app             - Flask app configured for testing (in.memory SQLite, tmp Chroma)
    client          - Flask test client for route tests
    db_session      - clean DB with tables created, rolled back after each test
    auth_headers    - JWT token for a pre-created test user (use in @jwt_required routes)
    mock_llm        - patches invoke_with_retry to return a canned response (no Ollama/API needed)
    chroma_dir      - temp dir for Chroma (isolated per test, deleted after)
    fixture_pdf     - absolute path to small 3-page sample PDF in tests/fixtures/
"""

import os
import sys
import pytest

# Make backend/ importable without installing as a package
# pytest runs from repo root; backend modules import each other as flat
# top-level imports (e.g. `from config import ...`). Adding backend/ to sys.path
# reproduces the same import environment as running app.py directly.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
    
# Set test env vars BEFORE importing config, so validate_config() passes & 
# no real secrets are needed in CI.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("LLM_MODEL", "qwen2.5:3b")
os.environ.setdefault("LOG_LEVEL", "WARNING")   # keep test output quiet


# app + client fixtures

@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """
    Flask app configured for testing.
    
    scope="session" — built once per test run (not per test), because
    creating the app, registering blueprints, and patching config is expensive.
    DB and Chroma fixtures handle per-test isolation below.
    
    Uses:
        - in-memory SQlite (no file on disk, discarded after the session)
        - a temp dir for Chroma (isolated from any real dev data)
    """
    
    chroma_path = str(tmp_path_factory.mktemp("chroma"))
    upload_path = str(tmp_path_factory.mktemp("uploads"))
    
    # Patch config values before app imports them
    import config
    config.CHROMA_DB_PATH = chroma_path
    config.UPLOAD_FOLDER = upload_path
    
    from app import app as flask_app
    
    flask_app.config.update({
        "TESTING":                  True,
        # The correct in-memory SQLite URI is "sqlite:///:memory:" (three slashes, trailing colon)
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "JWT_SECRET_KEY":           "test-jwt-secret",
        "SECRET_KEY":               "test-secret-key",
        "RATELIMIT_ENABLED":        False, # disable rate limiting in tests
    })
    
    # flask_limiter reads RATELIMIT_ENABLED from app.config only once, inside limiter.init_app(app) 
    # Setting app.config["RATELIMIT_ENABLED"]     after that point has no effect; flask-limiter already
    # cached its enabled/disabled state as plain attribute at init time.
    
    # Without this, auth_headers (called by n early every route test) hits /register and /login repeatedly across
    # whole session, and once AUTH_RATE_LIMIT's cap (5/min) is exceeded, every later test gets 429 instead of response
    # its actually testing for.
    
    # Setting limiter's `enabled` attribute directly is reliable, version-agnostic way to disable enforcement for whole test session
    # regardless of config-timing.
    from extensions import limiter as _limiter
    _limiter.enabled = False

    yield flask_app
    

@pytest.fixture(scope="session")
def client(app):
    # Flask test client — use this in route (Tier 3) tests.
    return app.test_client()


# Database fictures

@pytest.fixture(scope="session")
def _db(app):
    # Create all tables once per session, drrop them at end.
    # Internal fixture — tests use `db_session` below, not this directly.
    from extensions import db
    with app.app_context():
        db.create_all()
        yield db
        db.drop_all()
 
        
@pytest.fixture()
def db_session(_db, app):
    """
    Per-test DB session with automatic rollback.
    
    Each test gets a clean slate without recreationg the schema - 
    rollback is much faster than drop+create for large suites.
    """
    from extensions import db as _ext_db
    yield _ext_db
    _ext_db.session.rollback()
    

# Auth helper

@pytest.fixture()
def auth_headers(client, db_session):
    """
    Register + login a test user, return {'Authorization': 'Bearer <token>'}.
    
    use this in any test hittimg a @jwt_required route so you dont have to 
    repeat register/login dance in every test func.    
    """ 
    client.post("/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpassword123",
    })
    resp = client.post("/login", json={
        "email": "test@example.com",
        "password": "testpassword123",
    })
    token = resp.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


# LLM mock fixture

@pytest.fixture()
def mock_llm(monkeypatch):
    """
    Patch invoke_with_retry to return a canned LLM response.
    
    WHY: Tier 2 and 3 tests must not call a real LLM.
    Ollama might not br=e running in CI; hosted APIs cost quota and are
    non-detyerministic. we're testing pipeline (retrieval, context building,
     citations), not the LLM's prose quality.
     
    Patching invoke_with_retry (rather than the LLM object itself) is
    correct — it's the exact seam built for this purpose in llm_provider.py.
    Any test that calls ask_question() and imports mock_llm will get a
    predictable, instant response without any real LLM call. 
    """
    from unittest.mock import MagicMock
    
    fake_response = MagicMock()
    fake_response.content = "This is a mocked LLM answer for testing."
    
    monkeypatch.setattr(
        "services.rag_service.invoke_with_retry",
        lambda llm, prompt, **kwargs: fake_response,
    )
    return fake_response


# path helpers

@pytest.fixture()
def chroma_dir(tmp_path, monkeypatch):
    """
    Per-test isolated Chroma dir.
    
    Use this in Tier 2 tests that call ingest_pdf() directly — keeps 
    each test's vector data completely seperate so tests dont pollute each 
    others retrieval results.
    """
    import config
    chroma_path = str(tmp_path / "chroma")
    os.makedirs(chroma_path, exist_ok=True)
    monkeypatch.setattr(config, "CHROMA_DB_PATH", chroma_path)
    
    # Also patch the path inside rag_service module (it imported it at load time)
    import services.rag_service as rag
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", chroma_path)
    
    return chroma_path


@pytest.fixture(scope="session")
def fixture_pdf():
    # Absolute path to small 3-paged fixture pdf
    path = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pdf")
    assert os.path.exists(path), f"Fixture PDF not found at {path}"
    return path

"""
tmp_path_factory -> built-in pytest fixture that creates temp dirs and files for tests.
                    creates folders that can be shared across multiple tests.
monkeypatch      -> fixture that allows to temporarily change vars, funcs, methods, class attributes, env vars.
                    aftre tests, pytest automatically restores everythig.
MagicMock()      -> creates a fake obj that behaves like a real obj
"""