import base64
import json
import os
import secrets
import sys
from datetime import timedelta


def _executable_dir() -> str:
    """Directory where config.json must live: next to the running binary/script,
    never inside PyInstaller's temporary extraction folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir() -> str:
    """Directory where bundled read-only assets (templates/static) live."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _executable_dir()
RESOURCE_DIR = _resource_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Holds decrypted secrets / live connection state for the running process only.
# Populated on successful login, cleared on logout. Never written to disk.
runtime = {
    "api_key": None,
    "genai_client": None,
    "relay_url": None,
    "relay_token": None,
    "agent_secret": None,
    "password": None,  # kept in memory only, needed to encrypt/decrypt chat history on the fly
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError(
            "config.json topilmadi. Avval 'python3 setup.py' ni ishga tushiring."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_or_create_flask_secret() -> bytes:
    """Persist the session-signing key in config.json so page reloads within
    the same install don't invalidate the session cookie. Runtime secrets
    (api_key, password) still live only in memory and are never restored
    from disk, so a real process restart always requires logging in again."""
    if not os.path.exists(CONFIG_PATH):
        return secrets.token_bytes(32)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return secrets.token_bytes(32)

    if config.get("flask_secret"):
        return base64.b64decode(config["flask_secret"])

    key = secrets.token_bytes(32)
    config["flask_secret"] = base64.b64encode(key).decode("utf-8")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return key


def create_app():
    from flask import Flask, render_template

    app = Flask(
        __name__,
        template_folder=os.path.join(RESOURCE_DIR, "templates"),
        static_folder=os.path.join(RESOURCE_DIR, "static"),
    )
    app.secret_key = _load_or_create_flask_secret()
    app.permanent_session_lifetime = timedelta(days=30)

    from .auth import auth_bp
    from .chat import chat_bp
    from .computer import computer_bp
    from .events import events_bp
    from .messages import messages_bp
    from .onboarding import onboarding_bp, profile_bp
    from .social import social_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(computer_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(social_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    return app
