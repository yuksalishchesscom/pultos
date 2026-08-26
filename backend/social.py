import base64
import json

from flask import Blueprint, jsonify, request, session

from . import CONFIG_PATH, load_config, runtime
from . import social_client
from .security import decrypt_str, encrypt_str

social_bp = Blueprint("social", __name__, url_prefix="/api/social")


def _require_auth() -> bool:
    return session.get("authed") is True


@social_bp.route("/status", methods=["GET"])
def status():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    config = load_config()
    registered = bool(config.get("social_username"))
    return jsonify({"registered": registered, "connected": social_client.is_connected(), "username": config.get("social_username")})


@social_bp.route("/register", methods=["POST"])
def register():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if not username or len(username) < 3:
        return jsonify({"error": "Username kamida 3 belgidan iborat bo'lsin."}), 400
    if len(password) < 4:
        return jsonify({"error": "Parol kamida 4 belgidan iborat bo'lsin."}), 400

    result = social_client.register(username, password)
    if not result.get("ok"):
        return jsonify({"error": result.get("error") or "Ro'yxatdan o'tib bo'lmadi."}), 400

    config = load_config()
    salt = base64.urlsafe_b64decode(config["salt"])
    config["social_username"] = username
    config["encrypted_social_token"] = encrypt_str(password, runtime["password"], salt)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return jsonify({"ok": True, "username": username})


@social_bp.route("/chats", methods=["GET"])
def list_chats():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    return jsonify({"chats": social_client.get_chats()})


@social_bp.route("/find", methods=["GET"])
def find_user():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    username = (request.args.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Username kiriting."}), 400
    result = social_client.find_user(username)
    return jsonify(result)


@social_bp.route("/dm", methods=["POST"])
def start_dm():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Username kiriting."}), 400
    result = social_client.start_dm(username)
    return jsonify(result)


@social_bp.route("/group", methods=["POST"])
def create_group():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    members = data.get("members") or []
    if not name:
        return jsonify({"error": "Guruh nomini kiriting."}), 400
    result = social_client.create_group(name, members)
    return jsonify(result)


@social_bp.route("/<conversation_id>", methods=["GET"])
def get_messages(conversation_id):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    return jsonify({"messages": social_client.fetch_chat_messages(conversation_id)})


@social_bp.route("/<conversation_id>/send", methods=["POST"])
def send_message(conversation_id):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Xabar bo'sh bo'lishi mumkin emas."}), 400
    if not social_client.send_message(conversation_id, text):
        return jsonify({"error": "Yuborib bo'lmadi (aloqa yo'q)."}), 502
    return jsonify({"ok": True})


def try_auto_connect() -> None:
    """Called right after the main app login succeeds. If this install
    already has a PultOSgram identity, reconnect automatically; if not,
    the Xabarlar tab will offer to register one."""
    config = load_config()
    username = config.get("social_username")
    encrypted_token = config.get("encrypted_social_token")
    if not username or not encrypted_token:
        return
    try:
        salt = base64.urlsafe_b64decode(config["salt"])
        token = decrypt_str(encrypted_token, runtime["password"], salt)
    except Exception:
        return
    social_client.ensure_started(username, token)
