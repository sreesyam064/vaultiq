import os
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from config import UPLOAD_FOLDER
from extensions import db
from models import Document
from services import ingest_pdf

upload_bp = Blueprint("upload", __name__)
 
@upload_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_pdf():
    current_user_id = int(get_jwt_identity())
    
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    files = request.files.getlist("file")
    
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No file selected"}), 400
    
    results = []
    skipped = []
    
    for file in files:
        
        if not file or file.filename == "":
            continue
        
        # Check duplicate files before saving
        existing = Document.query.filter_by(
            user_id=current_user_id,
            filename=file.filename
        ).first()
        
        if existing:
            skipped.append(file.filename)
            continue    # skip this file, keep processing others
        
        # Save file to disk
        path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(path)
        
        # Save record to DB
        document = Document(
            user_id=current_user_id,
            filename=file.filename,
            filepath=path
        )
        db.session.add(document)
        db.session.commit()
        
        chunks = ingest_pdf(path, current_user_id)
        
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
    
    if not results and skipped:
        # Everything was duplicate, treat as conflict
        return jsonify(response), 409
    
    return jsonify(response), 200

