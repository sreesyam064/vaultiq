"""
Storage Service    
Abstracts "where uploaded PDFs live" behind one interface so routes and rag_service n
need to know whether a file is on local disk or in Cloudflare R2.

WHY THIS EXISTS
Previously upload_routes.py wrote directly to UPLOAD_FOLDER with oproblems.path.join(UPLOAD_FOLDER, secure_filename(file.filename)) — two 
problems that made R2 natural point to fix rather than just bolt on:
    1. No user-scoping: 2 users uploading "notes.pdf" overwrote each other's file on disk.
    2. filepath stored in DB was local path, meaningless on any other machine/container instance.
    
This module builds a collision-proof, user-scoped object key regardless of backend, and rag_service.ingest_pdf 
always receives a real local file path either way (PyPDFLoader needs one) — for R2, that means downloading
to a temp file first.

BACKEND SELECTION
config.STORAGE_BACKEND is "r2" or "local", auto-detected from whether R2_* env vars are set.
Local disk remains default for docker-compose.dev.yml / plain local dev — zero config needed.
"""
import os
import shutil
import logging
import tempfile
from contextlib import contextmanager

from config import STORAGE_BACKEND, UPLOAD_FOLDER

logger = logging.getLogger(__name__)

_r2_client = None


def _get_r2_client():
    # Lazy singletons, same pattern as embedding model / LLM client — avoids constructing a boto3 client
    # (& needing R2 creds) for any process/test that never actually touches storage.
    global _r2_client
    if _r2_client is None:
        import boto3
        from config import R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
        
        _r2_client = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            # R2 only supports (& requires) this signature version
            region_name="auto",
        )
    return _r2_client


def build_object_key(user_id, document_id, filename):
    """
    Canonical, collision-proof key: users/{user_id}/documents/{document_id}/{filename}
    
    Uses Postgres Document.id primary key — same id used to tag every chunk this document produces in ChromaDB 
    (metadata["document_id"] and each chunk's vector id) as shared identifier across Postgres, Chroma, R2, 
    enabling consistent lookup and deletion without seperate uuid or filaname-based matching.
    """
    safe_name = os.path.basename(filename).replace("/", "_").replace("\\", "_")
    return f"users/{user_id}/documents/{document_id}/{safe_name}"
    

def upload_local_file(local_path, object_key):
    # Push an already-staged file into active backend.
    
    # Call this AFTER ingest_pdf() has successfully processed local copy — that way
    # a file that fails PDF processing never gets written to R2 at all, & there's nothing to cleanup there on failure.
    if STORAGE_BACKEND == "r2":
        client = _get_r2_client()
        from config import R2_BUCKET_NAME
        client.upload_file(local_path, R2_BUCKET_NAME, object_key)
        logger.info(f"Uploaded '{object_key}' to R2 bucket '{R2_BUCKET_NAME}'")
    else:
        dest_path = os.path.join(UPLOAD_FOLDER, object_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copyfile(local_path, dest_path)
        logger.info(f"Copied '{object_key}' into local storage at '{dest_path}'")


@contextmanager
def local_copy(object_key):
    # Yielding a local filesystem path for a stored PDF.
    
    # R2 objects are downloaded to a temporary file and cleaned up afterward;
    # local-storage files are yielded directly. This provides the real file path
    # required by PyPDFLoader regardless of the storage backend.
    if STORAGE_BACKEND == "r2":
        client = _get_r2_client()
        from config import R2_BUCKET_NAME
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            client.download_file(R2_BUCKET_NAME, object_key, tmp_path)
            yield tmp_path
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    else:
        yield os.path.join(UPLOAD_FOLDER, object_key)
    
    
def delete_object(object_key):
    # Remove a stored file. Used by upload-failure cleanup today, & by a future document-delete endpoint.
    if STORAGE_BACKEND == "r2":
        client = _get_r2_client()
        from config import R2_BUCKET_NAME
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=object_key)
        logger.info(f"Deleted '{object_key}' from R2 bucket '{R2_BUCKET_NAME}'")
    else:
        local_path = os.path.join(UPLOAD_FOLDER, object_key)
        if os.path.exists(local_path):
            os.remove(local_path)
            logger.info(f"deleted local storage object '{local_path}'")
            