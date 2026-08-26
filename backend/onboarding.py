import base64
import json
import os
import secrets

from flask import Blueprint, jsonify, request, session

from . import CONFIG_PATH, load_config, runtime
from .security import encrypt_str, generate_salt, hash_password

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/api/setup")
profile_bp = Blueprint("profile", __name__, url_prefix="/api/profile")

HOME_AGENT_CONFIG_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "home_agent_config.json")


@onboarding_bp.route("/status", methods=["GET"])
def status():
    configured = os.path.exists(CONFIG_PATH)
    authed = session.get("authed") is True and bool(runtime.get("api_key"))
    profile = None
    if authed:
        try:
            profile = load_config().get("profile")
        except RuntimeError:
            profile = None
    return jsonify({"configured": configured, "authed": authed, "profile": profile})


@onboarding_bp.route("", methods=["POST"])
def create_setup():
    if os.path.exists(CONFIG_PATH):
        return jsonify({"ok": False, "error": "Ilova allaqachon sozlangan."}), 400

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    password_confirm = data.get("password_confirm") or ""
    api_key = (data.get("api_key") or "").strip()
    relay_url = (data.get("relay_url") or "").strip()

    if not username:
        return jsonify({"ok": False, "error": "Ismingizni kiriting."}), 400
    if len(password) < 4:
        return jsonify({"ok": False, "error": "Parol kamida 4 belgidan iborat bo'lsin."}), 400
    if password != password_confirm:
        return jsonify({"ok": False, "error": "Parollar mos kelmadi."}), 400
    if not api_key:
        return jsonify({"ok": False, "error": "Gemini API kalitini kiriting."}), 400

    salt = generate_salt()
    config = {
        "password_hash": hash_password(password),
        "salt": base64.urlsafe_b64encode(salt).decode("utf-8"),
        "encrypted_api_key": encrypt_str(api_key, password, salt),
        "flask_secret": base64.b64encode(secrets.token_bytes(32)).decode("utf-8"),
        "profile": {"username": username},
    }

    if relay_url:
        relay_token = secrets.token_urlsafe(32)
        agent_secret = secrets.token_urlsafe(32)
        config["relay_url"] = relay_url
        config["encrypted_relay_token"] = encrypt_str(relay_token, password, salt)
        config["encrypted_agent_secret"] = encrypt_str(agent_secret, password, salt)

        home_agent_config = {
            "relay_url": relay_url,
            "relay_token": relay_token,
            "agent_secret": agent_secret,
            "watch_paths": [],
        }
        with open(HOME_AGENT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(home_agent_config, f, indent=2)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    runtime["api_key"] = api_key
    runtime["genai_client"] = None
    runtime["relay_url"] = relay_url or None
    runtime["relay_token"] = config.get("encrypted_relay_token") and relay_token
    runtime["agent_secret"] = config.get("encrypted_agent_secret") and agent_secret
    runtime["password"] = password
    session.permanent = True
    session["authed"] = True

    if relay_url:
        from .relay_client import ensure_started

        ensure_started()

    return jsonify({"ok": True, "profile": config["profile"]})


def _require_auth() -> bool:
    return session.get("authed") is True and bool(runtime.get("api_key"))


@profile_bp.route("", methods=["PATCH"])
def update_profile():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Ismingizni kiriting."}), 400

    config = load_config()
    config["profile"] = {"username": username}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return jsonify({"ok": True, "profile": config["profile"]})
