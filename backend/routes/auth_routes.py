from sqlalchemy.exc import IntegrityError
import logging
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from extensions import db, limiter
from models import User
from config import AUTH_RATE_LIMIT

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Register
@auth_bp.route("/register", methods=["POST"])
@limiter.limit(AUTH_RATE_LIMIT)
def register():
    # request.get_json() (crashes/AttributeErrors on non-JSON bodies)
    data = request.get_json(silent=True) or {}
    
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    
    # Validate required fields
    if not username or not email or not password:
        return jsonify({"error": "All fields required"}), 400
    
    # Check duplicate username
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 409
    
    # Check duplicate email
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already exists"}), 409
    
    # hashing password
    hashed_password = generate_password_hash(password)
    
    new_user = User(
        username=username,
        email=email,
        password_hash=hashed_password
    )
    
    db.session.add(new_user)
    try:
        db.session.commit()   
    except IntegrityError:
        # A concurrent request won username/email uniqueness race between
        # our pre-checks above this commit.
        db.session.rollback()
        return jsonify({"error": "Username or email already exists"}), 409
    except Exception as e:
        db.session.riollback()
        logger.error(f"Registration commit failed for username='{username}': {e}", exc_info=True)
        return jsonify({"error": "Failed to register. Please try again"}), 500
    
    return jsonify({"message": "User registered successfully"}), 201
    
# Login
@auth_bp.route("/login", methods=["POST"])
@limiter.limit(AUTH_RATE_LIMIT)
def login():
    data = request.get_json(silent=True) or {}
    
    email = data.get("email")
    password = data.get("password")
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    user = User.query.filter_by(email=email).first()
    # think: SELECT * FROM users WHERE email = ? LIMIT 1;
    
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401
    
    if not check_password_hash(user.password_hash,password):
        return jsonify({"error": "Invalid email or password"}), 401

    logger.info(f"Login Successful for user_id={user.id}")
    
    token = create_access_token(identity=str(user.id))  # jwt prefer str over int
    
    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        }
    }), 200
    
# Profile    
@auth_bp.route("/profile", methods=["GET"]) 
@jwt_required()
def profile():
    current_user_id = get_jwt_identity()
    
    user = db.session.get(User, int(current_user_id))
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "message": "Access Granted",
        "user_id": current_user_id,
        "username": user.username,
        "email": user.email
    }), 200
    