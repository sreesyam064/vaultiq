import os
import logging
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from config import UPLOAD_FOLDER, MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB, MAX_FILES_PER_UPLOAD
from extensions import db
from models import Document
from services import ingest_pdf

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
    
    # files saves as UPLOAD_FOLDER/user_<id>/<filename> — previously same uploaded PDF would overwrite same shared path
    # and BOTH users' SQL rows would then silently point at whichever file's bytes happened to be on disk last — a cross-user data leak,
    # not just a naming clash. Now every user gets their own subdir so two different users uploading "notes.pdf" no longer collide on disk.
    user_upload_dir = os.path.join(UPLOAD_FOLDER, f"user_{current_user_id}")
    os.makedirs(user_upload_dir, exist_ok=True)
    
    results = []
    skipped = []
    errors  = []
    
    for file in files:
        
        if not file or file.filename == "":
            continue
        
        # file.fileanme is attacker-controlled and was previously used verbatim in os.path.join(ULOAD_FOLDER,
        # file.filename). A filename like "../../../etc/something" would be honoured by os.path.join,
        # allowing writes outside UPLOAD_FOLDER entirely(path traversal). 
        # secure_filename() strips path separators, ".." segments, & unsafe characters, 
        # returning a filesystem-safe basename.
        safe_filename= secure_filename(file.filename)
        
        if not safe_filename:
            errors.append({
                # secure_filename() can return "" for filenames that are entirely unsafe characters e.g. "../../" or "???,pdf"
                "file": file.filename,
                "reason": "Filename is invalid or unsafe. Please rename the file and try again.",
            })
            continue
        
        # Extension check on frontend (st.file_uploader(type=["pdf"])) was purely cosmetic, trivally bypassed by 
        # anyone calling this API directly. Now Enforcing it server-side too
        if not safe_filename.lower().endswith(".pdf"):
            errors.append({
                "file": file.filename,
                "reason": "Only PDF files are supported.",
            })
            continue
        
        # No size limit existed here. MAX_CONTENT_LENGTH (in app.py) covers whole request
        # this per-file check gives a specific, friendly msg identifinhg which file was too big
        # instead of whole request failing with generic 413.
        file_size = _get_file_size(file)
        if file_size > MAX_UPLOAD_SIZE_BYTES:
            errors.append({
                "file": file.filename,
                "reason": f"File exceeds the {MAX_UPLOAD_SIZE_MB}MB size limit.",
            })
            continue
        
        if file_size == 0:
            errors.append({
                "file": file.filename,
                "reason": "File is empty.",
            })
            continue
        
        # Verify actual PDF content, not just claimed extension.
        # Reads only first 5 bytes: cheap, no need to load whole file to check its signature.
        header = file.stream.read(len(PDF_MAGIC_BYTES))
        file.stream.seek(0)
        if header != PDF_MAGIC_BYTES:
            errors.append({
                "file": file.filename,
                "reason": "File does not appear to be a valid PDF.",
            })
            continue
          
        # Check duplicate files before saving
        # Uses SANITIZED filename: must match what's actually written to disk and what future
        # re-upload attempts will also sanitize to, or duplicate check & 
        # stored file would disgree with each other
        existing = Document.query.filter_by(
            user_id=current_user_id,
            filename=file.filename
        ).first()
        
        if existing:
            skipped.append(file.filename)
            continue    # skip this file, keep processing others
        
        # Save file to disk — now inside user's own subdir, using sanitized filename
        path = os.path.join(user_upload_dir, safe_filename)
        file.save(path)
        
        try:
            chunks = ingest_pdf(path, current_user_id)
        except Exception as e:
            logger.error(f"ingest_pdf failed for '{file.filename}' (user {current_user_id}): {e}", exc_info=True)
        
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as cleanup_err:
                logger.warning(f"Could not remove failed upload file '{path}': {cleanup_err}")
        
            errors.append({
                "file": file.filename,
                "reason": "Failed to process this document. Please try uploading it again."
            })
            continue
    
        # Save record to DB
        document = Document(
            user_id=current_user_id,
            filename=safe_filename,
            filepath=path
        )
        db.session.add(document)
        
        try:
            db.session.commit()
        except IntegrityError:
            # (user_id, filename) UniqueConstrain added to Document closes a race-condition window: 
            # 2 concurrent requests for same user + filename could both pass earlier SELECT-based duplicate check before either commits.
            # If that happens, LOSER of race lands here: rollback its own half-finished transaction, remove
            # file it just wrote and report this as normal duplicate rather than crashing with unhandled 500.
            db.session.rollback()
            logger.info(
                f"Concurrent duplicate upload detected for '{safe_filename}' "
                f"(user {current_user_id}) — treating as already uploaded."
            )
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
            skipped.append(safe_filename)
            continue
        
        results.append({
            "file": file.filename,
            "chunks": chunks,
            "status": "uploaded"
        })
        
    # Build response
    response = {}
    
    if results:
        response["uploaded"] = results
        
    if skipped:
        response["skipped"] = [
            {"file": f, "reason":"Already uploaded. Delete it first to re-upload."}
            for f in skipped
        ]
    
    if errors:
        response["errors"] = errors
    
    # Status code logic:
    #   - 200 -> any successful upload , even if some files were skipped/errored
    #   - 409 -> Nothing uploaded, but some were duplicated and none genuinely failed
    #   - 500 -> Nothing uploaded, and atleast one file genuinely failed to process
    #   (dintinguishes "you already did this" from "something went wrong,
    #   please retry" — errors are always retryable now, duplicates are not)
    if results:
        return jsonify(response), 200
    elif errors:
        return jsonify(response), 500
    elif skipped:
        return jsonify(response), 409
    
    return jsonify(response), 200

