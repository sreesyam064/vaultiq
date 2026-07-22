import os
import logging
import tempfile
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from config import UPLOAD_FOLDER, MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB, MAX_FILES_PER_UPLOAD
from extensions import db
from models import Document
from services import (
    ingest_pdf,
    delete_document_vectors,
    build_object_key,
    upload_local_file,
    delete_object,
)

logger = logging.getLogger(__name__)

upload_bp = Blueprint("upload", __name__)

#PDF file signature ("magic bytes"). Every valid PDF starts with this, regardless of what its filename.extension claims.
# Checking this instead of trusting extension catches a renamed ,exe/.html/whatever file .
PDF_MAGIC_BYTES = b"%PDF-"
 
def _get_file_size(file_storage) -> int:
    # Get a Werkzeug Filestorage's size without loading it fully into memory.
    # seel to end, read position, seek back to start so caller (file.save()) reads from beginning.
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    return size
 
def _validate_upload(file):
    """
    Server-side validation, run before the file ever touches disk or DB. 
    Returns an error dick (file/reason) if invalid, None if OK.
    
    Every one of these is a CLIENT error (bad input) — caller is responsible for keeping these in 
    a separate bucket from ingestion/ storage/DB failures, so a bad file neger gets reported as 500.
    """
    safe_filename = secure_filename(file.filename)
        
    if not safe_filename:
        # secure_filename() can return "" for filenames that are entirely unsafe characters e.g. "../../" or "???,pdf"
        return {
            "file": file.filename,
            "reason": "Filename is invalid or unsafe. Please rename the file and try again.",
        }
    
    # Extension check on frontend (st.file_uploader(type=["pdf"])) was purely cosmetic, trivally bypassed by 
    # anyone calling this API directly. Now Enforcing it server-side too
    if not safe_filename.lower().endswith(".pdf"):
        return {
            "file": file.filename,
            "reason": "Only PDF files are supported.",
        }
        
    # No size limit existed here. MAX_CONTENT_LENGTH (in app.py) covers whole request
    # this per-file check gives a specific, friendly msg identifinhg which file was too big
    # instead of whole request failing with generic 413.
    file_size = _get_file_size(file)
    if file_size == 0:
        return {
            "file": file.filename,
            "reason": "File is empty.",
        }
    if file_size > MAX_UPLOAD_SIZE_BYTES:
        return {
            "file": file.filename,
            "reason": f"File exceeds the {MAX_UPLOAD_SIZE_MB}MB size limit.",
        }
   
    # Verify actual PDF content, not just claimed extension.
    # Reads only first 5 bytes: cheap, no need to load whole file to check its signature.
    header = file.stream.read(len(PDF_MAGIC_BYTES))
    file.stream.seek(0)
    if header != PDF_MAGIC_BYTES:
        return {
            "file": file.filename,
            "reason": "File does not appear to be a valid PDF.",
        }
            
    return None

def _reconcile_failed_documents(document, document_id, current_user_id, storage_key=None, cleanup_vectors=True):
    """
    Best-effort cleanup after a partially failed document upload.

    Independently removes Chroma vectors, storage objects, and the DB row
    so one cleanup failure does not block the others. If DB deletion fails,
    marks the document as "failed" for later reconciliation.
    """
    if cleanup_vectors:
        try:
            delete_document_vectors(document_id, current_user_id)
        except Exception as e:
            logger.error(
                f"Cleanup: failed to delete Chroma vectors for document {document_id}: {e}",
                exc_info=True,
            )

    if storage_key:
        try:
            delete_object(storage_key)
        except Exception as e:
            logger.error(
                f"Cleanup: failed to delete storage object: '{storage_key}' for document {document_id}: {e}",
                exc_info=True,
            )
    
    try:
        db.session.delete(document)
        db.session.commit()
        return  # row removed successfully — don't fall through and re-insert it below
    except Exception as e:    
        db.session.rollback()
        logger.error(
            f"Cleanup: failed to delete Document row {document_id} — "
            f"marking status='failed' instead: {e}",
            exc_info=True,
        )
        
    try:
        # The rollback above expires in-memory object
        # Re-fetch it fresh rather than mutating a possibly-state/detached instance.
        document = db.session.get(type(document), document_id)
        if document is None:
            logger.critical(
                f"Cleanup: document  {document_id} vanished between delete failure and "
                f"fallback status update — manual reconciliation required for user "
                f"{current_user_id}."
            )
            return
        document.status = "failed"
        db.session.commit()    
    except Exception as e2:
        db.session.rollback()
        logger.critical(
            f"Cleanup: could not delete OR mark document {document_id} as failed — "
            f"manual reconciliation required for user {current_user_id}. Error: {e2}",
            exc_info=True,
        )

def _upload_single_file(file, current_user_id):
    """
    Handles one file end-to-end with compensating cleanup on every failure
    path. Returns (status, payload) where status is one of:
        "uploaded"      -> payload is the success dict
        "skipped"       -> payload is the (sanitized) filename
        "client_error"  -> payload is an error dict; bad input, not our fault
        "server_error"  -> payload is an error dict; ingestion/storage/DB
                            actually failed
 
    FLOW:
      1. Validate (client errors only — no disk/DB touched yet).
      2. Create the Document row FIRST, status="processing", filepath=None
         — gives us document.id before anything touches Chroma or storage,
         so document.id can be the one canonical identifier used by both
         the R2/local object key AND the Chroma metadata/vector ids.
      3. Stage the file to a temp dir, ingest into Chroma tagged with that
         document_id.
      4. Push the staged file to storage (R2/local) under a key built from
         that same document_id.
      5. Fill in filepath, flip status="ready", commit.
 
    Any failure after step 2 triggers _reconcile_failed_document() for
    whatever already succeeded, so a partial failure never leaves an
    orphaned DB row, orphaned Chroma vectors, or an orphaned storage object
    silently unaccounted for.
    """
    error = _validate_upload(file)
    if error:
        return "client_error", error
        
    safe_filename = secure_filename(file.filename)
    
    # Duplicate check. The UNIQUE(user_id, filename) DB constraint below
    # is the real guarantee against a race condition — this pre-check
    # just avoids the round trip through ingestion for a plain re-upload.
    # Uses the SANITIZED filename: must match what's actually stored and
    # what a future re-upload attempt will also sanitize to.
    existing = Document.query.filter_by(
        user_id=current_user_id,
        filename=safe_filename
    ).first()
    if existing:
        if existing.status == "failed":
            # stale row fro a prior failed upload. Itrs Chroma/storage cleanup already
            # ran when it was marked "failed" — this row itself is only thing left, and
            # only thing blocking retry via UNIQUE(user_id, filename) constraint.
            # Reap it so fresh upload below can proceed.
            try:
                db.session.delete(existing)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(
                    f"Failed to reap stale failed Document row for "
                    f"'{safe_filename}' (user {current_user_id}): {e}",
                    exc_info=True,
                )
                return "server_error", {
                    "file": safe_filename,
                    "reason": "Could not clear previous failed upload for this "
                               "filename. Please try again in a moment.",
                }
        else:
            return "skipped", safe_filename
    
    # Step 2: create the row first, to get document.id
    document = Document(
        user_id=current_user_id,
        filename=safe_filename,
        filepath=None,
        status="processing",
    )
    db.session.add(document)
    try:
        db.session.commit()
    except IntegrityError:
        # Someone else's concurrent request won the UNIQUE(user_id,
        # filename) race between our pre-check above and this commit.
        db.session.rollback()
        return "skipped", safe_filename
    except Exception as e:
        # Any other DB failure (connectivity, timeout, etc) — nothing has touched Chroma/storage yet,
        # so a plain rollback is enough. No document row exists to cleanup simce commit itself failed    
        db.session.rollback()
        logger.error(
            f"Initial DB commit failed for '{safe_filename}' (user {current_user_id}): {e}",
            exc_info=True
        )
        return "server_error", {
            "file": safe_filename,
            "reason": "Failed to save this document. Please try again in a moment.",
        }
    
    document_id = document.id
    
    # Step 3 + 4: stage locally, ingest, then push to storage.
    # WHY a temp dir (not tempfile.NamedTemporaryFile): ingest_pdf
    # derives the citation/metadata filename from os.path.basename(path),
    # so the staged file must be named exactly like the sanitized upload.
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            staged_path = os.path.join(tmp_dir, safe_filename)
        
            try:
                file.save(staged_path)
            except OSError as e:
                # Disk full, filesystem error, interrupted stream, etc.
                # Nothing touched Chroma/storage — just DB row to clean up.
                logger.error(
                    f"Failed to stage upload '{safe_filename}' (user {current_user_id}, doc {document_id}: {e})",
                    exc_info=True,
                )
                _reconcile_failed_documents(document, document_id, current_user_id, cleanup_vectors=False)
                return "server_error", {
                    "file": safe_filename,
                    "reason": "Failed to receive this file. Please try uploading it again.",
                }
        
            try:
                chunks = ingest_pdf(staged_path, current_user_id, document_id, filename=safe_filename)
            except Exception as e:
                logger.error(
                    f"ingest_pdf failed for '{safe_filename}' (user {current_user_id}, doc {document_id}): {e}",
                    exc_info=True,
                )
                # Ingestion embeds in batches —  a failure partway through can still have committed earlier batches to 
                # Chroma before exception was raised. Cleanup is idempotent (no-op if nothing written), so always
                # attempt it here rather than assuming "it raised, so nothing landed"
                _reconcile_failed_documents(document, document_id, current_user_id, cleanup_vectors=True)
                return "server_error", {
                    "file": safe_filename,
                    "reason": "Failed to process this document. Please try uploading it again.",
                }
            
            object_key = build_object_key(current_user_id, document_id, safe_filename)
            try:
                upload_local_file(staged_path, object_key)
            except Exception as e:
                logger.error(
                    f"Storage upload failed for '{safe_filename}' (user {current_user_id}, doc {document_id}: {e})",
                    exc_info=True,
                )
                # Chroma ingestion already succeeded — must be rolled back too, or we'd have vectors
                # with no matching document row. storage upload itself failed, so there's nothing left
                # at object_key to clean up.
                _reconcile_failed_documents(document, document_id, current_user_id, cleanup_vectors=True)
                return "server_error", {
                    "file": safe_filename,
                    "reason": "Processed successfully but failed to save the file. Please try again.",
                } 
    except Exception as e:
        # Catch-all for anything unexpected inside staging block that specific handlers above didnt anticipate — still
        # reconcile rather than letting it bubble as 500 with orphaned error.
        logger.error(
            f"Unexpected failure staging/ingesting '{safe_filename}' (user {current_user_id}, doc {document_id}: {e})",
            exc_info=True,
        ) 
        _reconcile_failed_documents(document, document_id, current_user_id, cleanup_vectors=True)
        
        return "server_error", {
            "file": safe_filename,
            "reason": "Failed to process this document. Please try uploading it again.",
        }
    
    # Step 5: fill in filepath, flip to ready, commit
    document.filepath = object_key
    document.status = "ready"
    try:
        db.session.commit()
    except Exception as e:
        # Both Chroma AND storage already succeeded — roll both back so
        # the failed DB commit doesn't leave orphans in either place.
        logger.error(
            f"DB commit failed after successful ingest+upload for '{safe_filename}' "
            "(user {current_user_id}, doc {document_id}): {e}",
            exc_info=True,
        )
        db.session.rollback()
        _reconcile_failed_documents(document, document_id, current_user_id, storage_key=object_key, cleanup_vectors=True)
        return "error", {
            "file": safe_filename,
            "reason": "Upload failed while saving. Please try again."
        }

    return "uploaded", {
        "file": safe_filename,
        "chunks": chunks,
        "status": "uploaded"
    }
     
 
@upload_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_pdf():
    current_user_id = int(get_jwt_identity())
    
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    files = request.files.getlist("file")
    
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No file selected"}), 400
    
    if len(files) > MAX_FILES_PER_UPLOAD:
        return jsonify({
            "error": f"Too many files in one upload. Maximun is {MAX_FILES_PER_UPLOAD}."
        }), 400
    
    results = []
    skipped = []
    client_errors = []
    server_errors = []
    
    for file in files:
        
        if not file or file.filename == "":
            continue
        
        status, payload = _upload_single_file(file, current_user_id)
        if status == "uploaded":
            results.append(payload)
        elif status == "skipped":
            skipped.append(payload)
        elif status == "client_error":
            client_errors.append(payload)
        else:
            server_errors.append(payload)
        
    # Build response
    response = {}
    
    if results:
        response["uploaded"] = results
        
    if skipped:
        response["skipped"] = [
            {"file": f, "reason":"Already uploaded. Delete it first to re-upload."}
            for f in skipped
        ]
    
    if client_errors or server_errors:
        response["errors"] = client_errors + server_errors
    
    # Status code logic:
    #   - 200 -> any successful upload , even if some files were skipped/errored
    #   - 409 -> Nothing uploaded, but some were duplicated and none genuinely failed
    #   - 500 -> Nothing uploaded, and atleast one file genuinely failed to process
    #   (dintinguishes "you already did this" from "something went wrong,
    #   please retry" — errors are always retryable now, duplicates are not)
    if results:
        return jsonify(response), 200
    elif server_errors:
        return jsonify(response), 500
    elif client_errors:
        return jsonify(response), 400
    elif skipped:
        return jsonify(response), 409
    
    return jsonify(response), 200


@upload_bp.route("/documents", methods=["GET"])
@jwt_required()
def list_documents():
    current_user_id = int(get_jwt_identity())
    docs = Document.query.filter_by(user_id=current_user_id).order_by(Document.uploaded_at.desc()).all()
    return jsonify([
        {"id": d.id, "filename": d.filename, "uploaded_at": d.uploaded_at.isoformat()}
        for d in docs
        # Hide rows mid-upload (filepath still NONE) AND rows mid-deletion (deletion_status="deleting") — 
        # both are transient states a document should never be presented as "normally available" in.
        if d.filepath is not None and d.deletion_status == "active"
    ]), 200


@upload_bp.route("/documents/<int:document_id>", methods=["DELETE"])
@jwt_required()
def delete_document(document_id):
    """
    Deletes a document across all three stores it lives in: Postgres row,
    Chroma vectors, and the R2/local storage object. document_id is the
    one identifier all three are keyed by, which is what makes this a
    single coordinated operation instead of three independent lookups by
    filename.
    
    
    Deletes a document from Postgres, ChromaDB, and R2/local storage with no 
    shared transaction across them, since they are 3 independent systems.

    The document is first marked "deleting" so it is no longer treated
    as active while cleanup runs. Cleanup operations are idempotent, so
    partially failed deletions can be safely retried.

    The database row is removed only after all cleanup succeeds.
    """
    current_user_id = int(get_jwt_identity())

    document = db.session.get(Document, document_id)
    if not document or document.user_id != current_user_id:
        return jsonify({"error": "Document not found"}), 404
    
    if document.deletion_status != "deleting":
        document.deletion_status = "deleting"
        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to mark doc {document_id} as deleting: {e}", exc_info=True)
            db.session.rollback()
            return jsonify({"error": "Failed to start deletion. Please try again."}), 500
    
    # From here on, every step is idempotent — safe to re-run on retry regardless of what
    # already succeeded on a previous sttempt.
    try:
        deleted_chunks = delete_document_vectors(document_id, current_user_id)
    except Exception as e:
        logger.error(f"Failed to delete Chroma vectors for doc {document_id}: {e}", exc_info=True)
        return jsonify({
            "error": "Failed to delete this document. Please try again.",
            "retryable": True,
            }), 500

    if document.filepath:
        try:
            delete_object(document.filepath)
        except Exception as e:
            logger.error(f"Failed to delete storage object for doc {document_id}: {e}", exc_info=True)
            return jsonify({
                "error": "Failed to delete the stored file. Please try again.",
                "retryable": True,
                }), 500

    # Delete the DB row only after external cleanup succeeds.
    try:
        db.session.delete(document)
        db.session.commit() 
    except Exception as e:
        # Chroma + storage already gone at this point — retrying this same DELETE will find both steps above
        # are now no-ops & just retry DB delete, so its safe to ask user to retry.
        db.session.rollback()
        logger.error(f"Failed to delete Document row {document_id}: {e}", exc_info=True)
        return jsonify({
                "error": "Failed to finalize document deletion. Please try again.",
                "retryable": True,
                }), 500
        
    return jsonify({
        "deleted": document_id,
        "chunks_removed": deleted_chunks,
    }), 200

 
