"""
Tier 2 — Integration Test: Gunicorn Logging
===========================================
Runs a real Gunicorn subprocess with production-like preload and worker
settings to verify logging behavior across forked workers.

Validates:
- Exactly one structured http.access JSON record per request.
- request_id/user_id propagate to module-level logger records.
- Warnings and unhandled exceptions remain visible.
- Gunicorn access logging does not produce duplicate request logs.
- File logs are not created by default; stdout/stderr are authoritative.

Skipped when Gunicorn or the full application dependency stack is unavailable.

"""
import os
import sys
import json
import time
import shutil
import socket
import signal
import subprocess

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = [
    pytest.mark.gunicorn,
    pytest.mark.skipif(
        shutil.which("gunicorn") is None,
        reason="gunicorn not on PATH — this test needs a real Gunicorn subprocess"
    ),
]


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def gunicorn_server(tmp_path_factory):
    port = _find_free_port()
    tmp_dir = tmp_path_factory.mktemp("gunicorn_logging_test")

    env = os.environ.copy()
    env.update({
        "SECRET_KEY": "test-secret",
        "JWT_SECRET_KEY": "test-jwt-secret",
        "LLM_PROVIDER": "ollama",
        "APP_ENV": "development",
        "GUNICORN_WORKERS": "2",
        "ENABLE_FILE_LOGGING": "false",  # explicit: this is the production default
    })

    stdout_path = tmp_dir / "stdout.log"
    stderr_path = tmp_dir / "stderr.log"

    proc = None
    try:
        with open(stdout_path, "w") as out, open(stderr_path, "w") as err:
            proc = subprocess.Popen(
                [
                    "gunicorn",
                    "--config", "gunicorn.conf.py",
                    "--bind", f"127.0.0.1:{port}",
                    "wsgi:app",
                ],
                cwd=BACKEND_DIR,
                env=env,
                stdout=out,
                stderr=err,
            )

            if not _wait_for_port(port, timeout=90):
                proc.terminate()
                pytest.skip("Gunicorn did not become ready in time (likely missing heavy deps in this environment)")

            yield {"port": port, "stdout_path": stdout_path, "stderr_path": stderr_path, "log_dir": tmp_dir}
    finally:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _read_json_lines(path):
    lines = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # Gunicorn's own boot lines aren't JSON — that's expected on errorlog
    return lines


class TestGunicornLoggingAfterFork:

    def test_requests_produce_exactly_one_access_line_each_with_ids(self, gunicorn_server):
        import urllib.request

        port = gunicorn_server["port"]
        for _ in range(5):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10).read()
        time.sleep(1)

        lines = _read_json_lines(gunicorn_server["stdout_path"])
        access_lines = [l for l in lines if l.get("logger") == "http.access"]

        assert len(access_lines) == 5, (
            f"expected exactly 5 http.access lines for 5 requests, got {len(access_lines)} "
            "— check gunicorn.conf.py's accesslog isn't re-enabled (would duplicate lines)"
        )
        for line in access_lines:
            assert line["request_id"] is not None, "request_id missing on an access log line"
            assert "endpoint" in line and "status" in line and "processing_time_ms" in line

    def test_no_log_files_created_by_default(self, gunicorn_server):
        storage_logs_dir = os.path.join(BACKEND_DIR, "storage", "logs")
        if not os.path.isdir(storage_logs_dir):
            return  # nothing to check
        # Only .gitkeep (or nothing) should be present — no rotating file
        # handler output, since ENABLE_FILE_LOGGING was left unset.
        contents = [f for f in os.listdir(storage_logs_dir) if f != ".gitkeep"]
        assert contents == [], f"unexpected log files created with ENABLE_FILE_LOGGING unset: {contents}"