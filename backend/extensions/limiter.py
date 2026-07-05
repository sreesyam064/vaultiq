"""
RAte Limiter Extension
======================
WHY THIS EXISTS:
    Hosted LLM free tiers enforce strict per-minute/per-day request quotas. 
    The /ask route is the only one that calls the LLM, so
    it's the one that needs protection — without a limit, one user (or a
    runaway frontend retry loop) can exhaust the app's entire quota and
    break it for every other user.
 
    Keyed by JWT identity (the logged-in user's ID) rather than IP address,
    because:
      - Multiple users behind the same NAT/office network share one IP —
        IP-based limiting would punish all of them for one person's usage.
      - A single user switching networks (phone -> wifi) would otherwise
        reset their limit, defeating the purpose.
    Falls back to remote IP for unauthenticated routes if ever needed.
"""

from flask_jwt_extended import get_jwt_identity
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def _rate_limit_key():
    # Key by logged-in user ID when available, else by IP.
    try:
        identity = get_jwt_identity()
        if identity:
            return f"user: {identity}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[],  # no global default; apply per-route via @limiter.limit(...)
    storage_uri="memory://",    # fine for a single-instance deploy (e.g. Render free tier)
)