import base64
import time

from cryptography.fernet import InvalidToken
from flask import Blueprint, jsonify, request, session

from . import load_config, runtime
from .security import decrypt_api_key, verify_password

auth_bp = Blueprint("auth", __name__, url_prefix="/api")

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
_login_attempts = {"count": 0, "locked_until": 0.0}


@auth_bp.route("/login", methods=["POST"])
def login():
    now = time.time()
    if now < _login_attempts["locked_until"]:
        wait = int(_login_attempts["locked_until"] - now) + 1
        return jsonify({"ok": False, "error": f"Juda ko'p urinish. {wait} soniyadan keyin qayta urinib ko'ring."}), 429

    data = request.get_json(silent=True) or {}
    password = data.get("password", "")

    try:
        config = load_config()
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    if not verify_password(password, config["password_hash"]):
        _login_attempts["count"] += 1
        if _login_attempts["count"] >= MAX_ATTEMPTS:
            _login_attempts["locked_until"] = now + LOCKOUT_SECONDS
            _login_attempts["count"] = 0
            return jsonify({"ok": False, "error": f"Juda ko'p urinish. {LOCKOUT_SECONDS} soniyadan keyin qayta urinib ko'ring."}), 429
        return jsonify({"ok": False, "error": "Xato parol!"}), 401

    _login_attempts["count"] = 0
    _login_attempts["locked_until"] = 0.0

    salt = base64.urlsafe_b64decode(config["salt"])
    try:
        api_key = decrypt_api_key(config["encrypted_api_key"], password, salt)

        relay_url = config.get("relay_url")
        relay_token = None
        agent_secret = None
        if config.get("encrypted_relay_token") and config.get("encrypted_agent_secret"):
            relay_token = decrypt_api_key(config["encrypted_relay_token"], password, salt)
            agent_secret = decrypt_api_key(config["encrypted_agent_secret"], password, salt)
    except InvalidToken:
        return jsonify({"ok": False, "error": "Sirlarni ochib boʻlmadi."}), 500

    runtime["api_key"] = api_key
    runtime["genai_client"] = None
    runtime["relay_url"] = relay_url
    runtime["relay_token"] = relay_token
    runtime["agent_secret"] = agent_secret
    runtime["password"] = password
    session.permanent = True
    session["authed"] = True

    from .relay_client import ensure_started
    from .social import try_auto_connect

    ensure_started()
    try_auto_connect()

    return jsonify({"ok": True, "relay_configured": bool(relay_url), "profile": config.get("profile")})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    runtime["api_key"] = None
    runtime["genai_client"] = None
    runtime["relay_url"] = None
    runtime["relay_token"] = None
    runtime["agent_secret"] = None
    runtime["password"] = None

    from .relay_client import stop as stop_relay
    from .social_client import stop as stop_social

    stop_relay()
    stop_social()

    return jsonify({"ok": True})
