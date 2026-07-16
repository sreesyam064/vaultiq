from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from extensions import db, limiter
from models import Document, ChatSession, Message   
from services import ask_question
from config import ASK_RATE_LIMIT

chat_bp = Blueprint("chat", __name__)

# Create Session
@chat_bp.route("/chat/session", methods=["POST"])
@jwt_required()
def create_session():
    current_user_id = int(get_jwt_identity())
    
    session = ChatSession(user_id=current_user_id)
    db.session.add(session)
    db.session.commit()
    
    return jsonify({"session_id": session.id}), 201
    
# Get Chat History
@chat_bp.route("/chat/<int:session_id>", methods=["GET"])
@jwt_required()
def get_chat(session_id):
    current_user_id = int(get_jwt_identity())
    session = db.session.get(ChatSession, session_id)
    if not session or session.user_id != current_user_id:
        return jsonify({"error": "Session not found"}), 404
    
    messages = Message.query.filter_by(session_id=session_id).all()
    
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]
        
    return jsonify(history), 200

# List All Sessions
@chat_bp.route("/chat/sessions", methods=["GET"])
@jwt_required()
def get_sessions():
    current_user_id = int(get_jwt_identity())
    
    sessions = ChatSession.query.filter_by(user_id=current_user_id).order_by(ChatSession.created_id.desc()).all()
    
    result = [
        {"id": s.id, "title": s.title}
        for s in sessions
    ]
    
    return jsonify(result), 200

# Ask Question
# limiter.limit() is keyed per-JWT-identity
# so one user spamming questions cant exhaust the quota for everyone else.
@chat_bp.route("/ask", methods=["POST"])
@jwt_required()
@limiter.limit(ASK_RATE_LIMIT)
def ask():
    data = request.get_json()
    
    session_id = data.get("session_id")
    question = data.get("question")
    if not session_id or not question:
        return jsonify({"error": "session_id and question are required"}), 400
    
    question = question.strip()
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400
    
    current_user_id = int(get_jwt_identity())
    
    # Verify session ownership before answering
    session = db.session.get(ChatSession, session_id)
    if not session or session.user_id != current_user_id:
        return jsonify({"error": "Session not found"}), 404
    
    # Check user has at least one document uploaded
    has_docs = Document.query.filter_by(user_id=current_user_id).first()
    if not has_docs:
        return jsonify({"error": "No documents uploaded. Please upload a PDF first."}), 400
    
    # Save user message
    user_message = Message(
        session_id=session_id,
        role="user",
        content=question
    )
    db.session.add(user_message)
    
    # Auto-title the session from the first question
    if session.title is None:
        session.title = question[:40]
        
    # Call RAG service
    result = ask_question(question, current_user_id)
    
    # Save assistant message
    assistant_message = Message(
        session_id=session_id,
        role="assistant",
        content=result["answer"]
    )
    db.session.add(assistant_message)
    db.session.commit()
    
    return jsonify(result), 200
               