import base64
import json
import os
import re
import time
import uuid

from flask import Blueprint, jsonify, request, send_from_directory, session
from google.genai import types

from . import BASE_DIR, relay_client, runtime
from .chat import MODEL_NAME, _get_client

computer_bp = Blueprint("computer", __name__, url_prefix="/api/computer")

ALLOWED_ACTIONS = {
    "shell", "screenshot", "lock", "restart", "shutdown",
    "open_app", "close_app", "report", "transfer_images",
    "browser_history", "app_usage_report",
}

SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")
GALLERY_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

# ---------- Rule-based fallback (used if Gemini is unavailable) ----------

_SCREENSHOT_WORDS = (
    "skrinshot", "skrin shot", "screenshot", "rasmga ol", "rasm ol",
    "ekran rasmi", "ekrandan rasm", "ekran rasmini ol",
)
_LOCK_WORDS = ("qulfla", "qulflab", "lock")
_RESTART_WORDS = ("qayta yoq", "qayta ishga tushir", "restart", "reboot")
_SHUTDOWN_WORDS = ("o'chir", "ochir", "o‘chir", "shutdown")
_REPORT_WORDS = ("hisobot", "holati qanday", "status ber", "report")
_BROWSER_HISTORY_WORDS = ("sayt tarixi", "brauzer tarixi", "internet tarixi", "qaysi saytlar")
_APP_USAGE_WORDS = ("dasturlar tarixi", "nima ishlatdim", "qaysi dasturlarni", "dasturlardan foydalanish")

_OPEN_APP_PATTERNS = (
    re.compile(r"^(.+?)\s+ni ochib ber$"),
    re.compile(r"^(.+?)\s+ochib ber$"),
    re.compile(r"^(.+?)\s+ni och$"),
    re.compile(r"^(.+?)\s+dasturini och$"),
    re.compile(r"^och\s+(.+)$"),
)
_CLOSE_APP_PATTERNS = (
    re.compile(r"^(.+?)\s+ni yopib qoʻy$"),
    re.compile(r"^(.+?)\s+ni yop$"),
    re.compile(r"^(.+?)\s+yopib ber$"),
    re.compile(r"^(.+?)\s+dasturini yop$"),
    re.compile(r"^yop\s+(.+)$"),
)


def interpret_command_rules(text: str):
    """Small rule-based Uzbek intent matcher, used as a fallback when the
    Gemini classifier is unavailable. Falls back further to treating the
    text as a literal shell command, preserving old console behaviour."""
    lowered = text.strip().lower()

    if any(w in lowered for w in _RESTART_WORDS):
        return "restart", {}
    if any(w in lowered for w in _SHUTDOWN_WORDS):
        return "shutdown", {}
    if any(w in lowered for w in _LOCK_WORDS):
        return "lock", {}
    if any(w in lowered for w in _SCREENSHOT_WORDS):
        return "screenshot", {}
    if any(w in lowered for w in _BROWSER_HISTORY_WORDS):
        return "browser_history", {}
    if any(w in lowered for w in _APP_USAGE_WORDS):
        return "app_usage_report", {}
    if any(w in lowered for w in _REPORT_WORDS):
        return "report", {}

    for pattern in _CLOSE_APP_PATTERNS:
        m = pattern.match(lowered)
        if m:
            app = m.group(1).strip()
            if app:
                return "close_app", {"app": app}

    for pattern in _OPEN_APP_PATTERNS:
        m = pattern.match(lowered)
        if m:
            app = m.group(1).strip()
            if app:
                return "open_app", {"app": app}

    return "shell", {"cmd": text}


# ---------- Gemini-based interpretation (primary path) ----------

NL_SYSTEM_PROMPT = """Sen uy kompyuterini boshqaruvchi tizimsan. Foydalanuvchi o'zbek tilida \
yozgan buyruqni quyidagi amallardan aynan biriga aylantirishing kerak va FAQAT JSON \
formatida javob ber, boshqa hech qanday matn yozma.

Ruxsat etilgan amallar:
{"action": "screenshot"} - ekrandan skrinshot olish
{"action": "lock"} - kompyuterni qulflash
{"action": "restart"} - kompyuterni qayta yuklash
{"action": "shutdown"} - kompyuterni o'chirish
{"action": "open_app", "app": "<dastur nomi>"} - dastur ochish (masalan firefox, nautilus, gedit, code)
{"action": "close_app", "app": "<dastur nomi>"} - ishlab turgan dasturni yopish
{"action": "report"} - kompyuter holati haqida hisobot (disk, xotira, uptime, IP)
{"action": "transfer_images", "folder": "<papka manzili>"} - berilgan papkadagi rasmlarni fleshkaga o'tkazish
{"action": "browser_history", "hours": <son, ixtiyoriy>} - qaysi saytlarga kirilgani, qancha vaqt va qachon (Firefox/Chrome tarixidan)
{"action": "app_usage_report", "hours": <son, ixtiyoriy>} - qaysi dasturlar qachon ochilib-yopilgani va qancha ishlatilgani
{"action": "shell", "cmd": "<bash buyrug'i>"} - faqat foydalanuvchi aniq texnik/bash buyrug'ini yozgan bo'lsa

Agar foydalanuvchi biror papka nomini aniq aytmasa (masalan "rasmlarni o'tkaz"), \
folder qiymatini "~/Pictures" deb ol. Agar "hours" aytilmasa, uni butunlay qo'ymang \
(standart qiymat ishlatiladi)."""


def interpret_command_ai(text: str):
    if not runtime.get("api_key"):
        raise RuntimeError("api_key yoʻq")
    client = _get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f'Foydalanuvchi buyrugʻi: "{text}"',
        config=types.GenerateContentConfig(
            system_instruction=NL_SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    data = json.loads(response.text)
    action = data.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"notanish amal: {action}")
    payload = {k: v for k, v in data.items() if k != "action"}
    return action, payload


def interpret_command(text: str):
    try:
        return interpret_command_ai(text)
    except Exception:
        return interpret_command_rules(text)


def _require_auth() -> bool:
    return session.get("authed") is True


def _save_gallery_image(image_bytes: bytes, ext: str) -> str:
    now = time.localtime()
    rel_dir = os.path.join(f"{now.tm_year:04d}", f"{now.tm_mon:02d}", f"{now.tm_mday:02d}")
    abs_dir = os.path.join(SCREENSHOTS_DIR, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    filename = f"{time.strftime('%H-%M-%S', now)}_{uuid.uuid4().hex[:6]}{ext}"
    with open(os.path.join(abs_dir, filename), "wb") as f:
        f.write(image_bytes)
    return "/".join([rel_dir.replace(os.sep, "/"), filename])


def _execute(action: str, payload: dict) -> dict:
    result = relay_client.send_command(action, payload)

    if action == "screenshot" and result.get("image_base64"):
        try:
            result["screenshot_path"] = _save_gallery_image(
                base64.b64decode(result["image_base64"]), ".png"
            )
        except Exception:
            pass

    elif action == "transfer_images" and result.get("images"):
        saved = 0
        for img in result["images"]:
            try:
                name = img.get("name", "")
                ext = os.path.splitext(name)[1].lower() or ".png"
                _save_gallery_image(base64.b64decode(img["data"]), ext)
                saved += 1
            except Exception:
                continue
        result["saved_to_gallery"] = saved
        result.pop("images", None)  # already persisted to disk, keep the response light

    return result


@computer_bp.route("/status", methods=["GET"])
def status():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    if not runtime.get("relay_url"):
        return jsonify({"configured": False})
    return jsonify({"configured": True, **relay_client.get_state()})


@computer_bp.route("/command", methods=["POST"])
def command():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    if not runtime.get("relay_url"):
        return jsonify({"error": "Uy kompyuteriga ulanish hali sozlanmagan."}), 400

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    payload = data.get("payload") or {}

    if action not in ALLOWED_ACTIONS:
        return jsonify({"error": "Notoʻgʻri amal."}), 400

    return jsonify(_execute(action, payload))


@computer_bp.route("/nl_command", methods=["POST"])
def nl_command():
    """Console input as free Uzbek text: Gemini figures out the intent
    (falls back to simple keyword rules if that fails), then we run it."""
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    if not runtime.get("relay_url"):
        return jsonify({"error": "Uy kompyuteriga ulanish hali sozlanmagan."}), 400

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Buyruq bo'sh."}), 400

    action, payload = interpret_command(text)
    result = _execute(action, payload)
    result["interpreted_action"] = action
    return jsonify(result)


@computer_bp.route("/screenshots", methods=["GET"])
def list_screenshots():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401

    groups = {}
    if os.path.isdir(SCREENSHOTS_DIR):
        for year in sorted(os.listdir(SCREENSHOTS_DIR), reverse=True):
            year_path = os.path.join(SCREENSHOTS_DIR, year)
            if not os.path.isdir(year_path):
                continue
            for month in sorted(os.listdir(year_path), reverse=True):
                month_path = os.path.join(year_path, month)
                if not os.path.isdir(month_path):
                    continue
                for day in sorted(os.listdir(month_path), reverse=True):
                    day_path = os.path.join(month_path, day)
                    if not os.path.isdir(day_path):
                        continue
                    files = sorted(
                        (f for f in os.listdir(day_path) if f.lower().endswith(GALLERY_EXTENSIONS)),
                        reverse=True,
                    )
                    if not files:
                        continue
                    groups[f"{year}-{month}-{day}"] = [f"{year}/{month}/{day}/{f}" for f in files]

    return jsonify({"groups": groups})


@computer_bp.route("/screenshots/<path:relpath>", methods=["GET"])
def serve_screenshot(relpath):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    return send_from_directory(SCREENSHOTS_DIR, relpath)
