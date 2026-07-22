"""
Tier 1 — Unit Tests: Storage Servives

Pure logic + local-backend round-trip tests for storage_service.py.
No network, no real R2 bucket — R2 path is verified by mocking boto3.
"""

import os
import sys
import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

    
class TestBuildObjectKey:
    
    def test_basic_key_shape(self):
        from services import build_object_key
        key = build_object_key(user_id=7, document_id=42, filename="report.pdf")
        assert key == "users/7/documents/42/report.pdf"
        
    def test_strips_path_separators_from_filename(self):
        # Filename should albeady be sanitized by secure_filename() upstream,
        # but build_object_key must not blindly trust it either
        from services import build_object_key
        key = build_object_key(user_id=1, document_id=1, filename="../../etc/passwd.pdf")
        assert "../" not in key
        assert key == "users/1/documents/1/passwd.pdf"
        
    def test_different_documents_never_collide(self):
        from services.storage_service import build_object_key
        key_a = build_object_key(user_id=1, document_id=1, filename="notes.pdf")
        key_b = build_object_key(user_id=1, document_id=2, filename="notes.pdf")
        assert key_a != key_b
        

class TestLocalBackend:
    # STORAGE_BACKEND to "local" in tests, so these exercise real local-disk code path.
    
    def test_upload_then_local_copy_roundtrip(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "STORAGE_BACKEND", "local")
        monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
 
        import services.storage_service as storage
        monkeypatch.setattr(storage, "STORAGE_BACKEND", "local")
        monkeypatch.setattr(storage, "UPLOAD_FOLDER", str(tmp_path))
 
        src = tmp_path / "staged.pdf"
        src.write_bytes(b"%PDF-1.4 fake content")
 
        object_key = storage.build_object_key(user_id=1, document_id=1, filename="staged.pdf")
        storage.upload_local_file(str(src), object_key)
 
        with storage.local_copy(object_key) as path:
            assert os.path.exists(path)
            with open(path, "rb") as f:
                assert f.read() == b"%PDF-1.4 fake content"
                
    def test_delete_object_removes_file(self, tmp_path, monkeypatch):
        import services.storage_service as storage
        monkeypatch.setattr(storage, "STORAGE_BACKEND", "local")
        monkeypatch.setattr(storage, "UPLOAD_FOLDER", str(tmp_path))
 
        src = tmp_path / "to_delete.pdf"
        src.write_bytes(b"%PDF-1.4 x")
        object_key = storage.build_object_key(user_id=1, document_id=1, filename="to_delete.pdf")
        storage.upload_local_file(str(src), object_key)
 
        stored_path = os.path.join(str(tmp_path), object_key)
        assert os.path.exists(stored_path)
 
        storage.delete_object(object_key)
        assert not os.path.exists(stored_path)
 
    def test_delete_object_missing_file_does_not_raise(self, tmp_path, monkeypatch):
        import services.storage_service as storage
        monkeypatch.setattr(storage, "STORAGE_BACKEND", "local")
        monkeypatch.setattr(storage, "UPLOAD_FOLDER", str(tmp_path))
 
        # Deleting a key that was never uploaded should be a safe no-op —
        # this path is hit during upload-failure cleanup.
        storage.delete_object("users/1/documents/999/never_existed.pdf")
        
        
class TestR2Backend:
    """
    Verifies the R2 code path constructs a valid boto3 client and calls the
    right S3-compatible methods — without touching a real network or bucket.
    """
 
    def test_r2_client_constructed_with_correct_args(self, monkeypatch):
        import services.storage_service as storage
        import config
 
        monkeypatch.setattr(config, "R2_ENDPOINT_URL", "https://acct123.r2.cloudflarestorage.com")
        monkeypatch.setattr(config, "R2_ACCESS_KEY_ID", "fake-key-id")
        monkeypatch.setattr(config, "R2_SECRET_ACCESS_KEY", "fake-secret")
 
        # Reset the module-level singleton so this test gets a fresh client.
        monkeypatch.setattr(storage, "_r2_client", None)
 
        captured = {}
 
        class FakeBoto3:
            @staticmethod
            def client(service_name, **kwargs):
                captured["service_name"] = service_name
                captured.update(kwargs)
                return "fake-client-object"
 
        monkeypatch.setitem(sys.modules, "boto3", FakeBoto3)
 
        client = storage._get_r2_client()
 
        assert client == "fake-client-object"
        assert captured["service_name"] == "s3"
        assert captured["endpoint_url"] == "https://acct123.r2.cloudflarestorage.com"
        assert captured["aws_access_key_id"] == "fake-key-id"
        assert captured["aws_secret_access_key"] == "fake-secret"
        assert captured["region_name"] == "auto"
 
    def test_r2_upload_calls_upload_file(self, monkeypatch):
        import services.storage_service as storage
        import config
 
        monkeypatch.setattr(storage, "STORAGE_BACKEND", "r2")
        monkeypatch.setattr(config, "R2_BUCKET_NAME", "vaultiq-uploads")
 
        calls = []
 
        class FakeClient:
            def upload_file(self, local_path, bucket, key):
                calls.append((local_path, bucket, key))
 
        monkeypatch.setattr(storage, "_get_r2_client", lambda: FakeClient())
 
        storage.upload_local_file("/tmp/whatever.pdf", "users/1/documents/1/whatever.pdf")
 
        assert calls == [("/tmp/whatever.pdf", "vaultiq-uploads", "users/1/documents/1/whatever.pdf")]
 
    def test_r2_delete_calls_delete_object(self, monkeypatch):
        import services.storage_service as storage
        import config
 
        monkeypatch.setattr(storage, "STORAGE_BACKEND", "r2")
        monkeypatch.setattr(config, "R2_BUCKET_NAME", "vaultiq-uploads")
 
        calls = []
 
        class FakeClient:
            def delete_object(self, Bucket, Key):
                calls.append((Bucket, Key))
 
        monkeypatch.setattr(storage, "_get_r2_client", lambda: FakeClient())
 
        storage.delete_object("users/1/documents/1/whatever.pdf")
 
        assert calls == [("vaultiq-uploads", "users/1/documents/1/whatever.pdf")]