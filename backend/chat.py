import base64
import json
import logging
import mimetypes
import os
import time
import uuid

from flask import Blueprint, Response, jsonify, request, session, stream_with_context
from google import genai
from google.genai import types

from . import BASE_DIR, load_config, runtime
from .security import decrypt_str, encrypt_str

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")

MODEL_NAME = "gemini-3.6-flash"

SYSTEM_INSTRUCTION = (
    "Sen PultOS-Flesh ilovasidagi yordamchi sun'iy intellektsan. "
    "Foydalanuvchiga oddiy, tushunarli o'zbek tilida, qisqa va aniq javob ber."
)

STORE_PATH = os.path.join(BASE_DIR, "chat_history.json")
MAX_MESSAGES_PER_CONV = 200
MAX_CONTEXT_MESSAGES = 30
TITLE_MAX_LEN = 40


def _require_auth() -> bool:
    return session.get("authed") is True and bool(runtime.get("api_key"))


def _get_client():
    if runtime.get("genai_client") is None:
        runtime["genai_client"] = genai.Client(api_key=runtime["api_key"])
    return runtime["genai_client"]


def _new_conversation() -> dict:
    now = time.time()
    return {"id": uuid.uuid4().hex, "title": "Yangi suhbat", "created": now, "updated": now, "messages": []}


def _load_store() -> dict:
    if not os.path.exists(STORE_PATH):
        return {"conversations": []}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            blob = json.load(f)
        config = load_config()
        salt = base64.urlsafe_b64decode(config["salt"])
        raw = decrypt_str(blob["data"], runtime["password"], salt)
        data = json.loads(raw)
    except Exception:
        return {"conversations": []}

    if isinstance(data, list):
        # Legacy flat-history format from before multi-conversation support.
        if not data:
            return {"conversations": []}
        conv = _new_conversation()
        conv["title"] = "Eski suhbat"
        conv["messages"] = data
        conv["created"] = data[0].get("ts", conv["created"])
        conv["updated"] = data[-1].get("ts", conv["updated"])
        return {"conversations": [conv]}

    return data if isinstance(data, dict) and "conversations" in data else {"conversations": []}


def _save_store(store: dict) -> None:
    config = load_config()
    salt = base64.urlsafe_b64decode(config["salt"])
    encrypted = encrypt_str(json.dumps(store), runtime["password"], salt)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump({"data": encrypted}, f)


def _find_conversation(store: dict, conv_id: str) -> dict | None:
    for conv in store["conversations"]:
        if conv["id"] == conv_id:
            return conv
    return None


def _conversation_summary(conv: dict) -> dict:
    last = conv["messages"][-1] if conv["messages"] else None
    return {
        "id": conv["id"],
        "title": conv["title"],
        "updated": conv["updated"],
        "preview": (last["text"][:60] if last else ""),
    }


def _derive_title(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= TITLE_MAX_LEN:
        return text or "Yangi suhbat"
    return text[:TITLE_MAX_LEN].rstrip() + "…"


def _build_contents(conv: dict, new_parts: list):
    contents = []
    for msg in conv["messages"][-MAX_CONTEXT_MESSAGES:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["text"]}]})
    contents.append({"role": "user", "parts": new_parts})
    return contents


TRANSIENT_MARKERS = ("429", "500", "502", "503", "timeout", "unavailable", "deadline")


def _friendly_error(exc: Exception) -> str:
    logger.exception("Gemini so'rovida xatolik")
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "resource_exhausted" in msg:
        return "So'rovlar chegarasiga yetdingiz. Birozdan keyin qayta urinib ko'ring."
    if "timeout" in msg or "deadline" in msg:
        return "Javob olishda vaqt tugadi. Qayta urinib ko'ring."
    if "unauthenticated" in msg or "api key" in msg or "401" in msg or "403" in msg or "permission" in msg:
        return "AI xizmatiga ulanishda muammo. API kalitni tekshiring."
    if "unavailable" in msg or "connection" in msg or "network" in msg or "dns" in msg:
        return "Internet aloqasi yo'q yoki server javob bermayapti."
    return "Xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring."


def _generate(conv: dict, new_parts: list) -> str:
    client = _get_client()
    contents = _build_contents(conv, new_parts)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
            )
            return response.text
        except Exception as exc:  # noqa: BLE001 - broad on purpose, classified below
            last_exc = exc
            transient = any(marker in str(exc).lower() for marker in TRANSIENT_MARKERS)
            if not transient or attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise last_exc  # pragma: no cover - unreachable, satisfies type checkers


def _generate_stream(conv: dict, new_parts: list):
    client = _get_client()
    contents = _build_contents(conv, new_parts)
    return client.models.generate_content_stream(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
    )


def _append_turn(store: dict, conv: dict, user_text: str, ai_text: str) -> None:
    now = time.time()
    if not conv["messages"]:
        conv["title"] = _derive_title(user_text)
    conv["messages"].append({"role": "user", "text": user_text, "ts": now})
    conv["messages"].append({"role": "ai", "text": ai_text, "ts": now})
    conv["messages"] = conv["messages"][-MAX_MESSAGES_PER_CONV:]
    conv["updated"] = now
    _save_store(store)


@chat_bp.route("/conversations", methods=["GET"])
def list_conversations():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    store = _load_store()
    convs = sorted(store["conversations"], key=lambda c: c["updated"], reverse=True)
    return jsonify({"conversations": [_conversation_summary(c) for c in convs]})


@chat_bp.route("/conversations", methods=["POST"])
def create_conversation():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    store = _load_store()
    conv = _new_conversation()
    store["conversations"].append(conv)
    _save_store(store)
    return jsonify(_conversation_summary(conv))


@chat_bp.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    store = _load_store()
    conv = _find_conversation(store, conv_id)
    if conv is None:
        return jsonify({"error": "Suhbat topilmadi."}), 404
    return jsonify({"id": conv["id"], "title": conv["title"], "messages": conv["messages"]})


@chat_bp.route("/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    store = _load_store()
    store["conversations"] = [c for c in store["conversations"] if c["id"] != conv_id]
    _save_store(store)
    return jsonify({"ok": True})


def _resolve_conversation(store: dict, conv_id: str | None) -> dict:
    if conv_id:
        conv = _find_conversation(store, conv_id)
        if conv is not None:
            return conv
    conv = _new_conversation()
    store["conversations"].append(conv)
    return conv


@chat_bp.route("/text", methods=["POST"])
def chat_text():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Xabar bo'sh bo'lishi mumkin emas."}), 400

    store = _load_store()
    conv = _resolve_conversation(store, data.get("conversation_id"))

    try:
        reply = _generate(conv, [{"text": message}])
        _append_turn(store, conv, message, reply)
        return jsonify({"reply": reply, "conversation_id": conv["id"], "title": conv["title"]})
    except Exception as exc:
        return jsonify({"error": _friendly_error(exc)}), 500


@chat_bp.route("/stream", methods=["POST"])
def chat_stream():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Xabar bo'sh bo'lishi mumkin emas."}), 400

    store = _load_store()
    conv = _resolve_conversation(store, data.get("conversation_id"))

    def generate():
        chunks: list[str] = []
        try:
            for piece in _generate_stream(conv, [{"text": message}]):
                text = getattr(piece, "text", None)
                if text:
                    chunks.append(text)
                    yield f"data: {json.dumps({'delta': text})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': _friendly_error(exc)})}\n\n"
            return

        reply = "".join(chunks)
        if reply:
            _append_turn(store, conv, message, reply)
        yield f"data: {json.dumps({'done': True, 'conversation_id': conv['id'], 'title': conv['title']})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _chat_with_file(field_name: str, default_caption: str, label: str):
    if field_name not in request.files:
        return jsonify({"error": "Fayl topilmadi."}), 400

    upload = request.files[field_name]
    caption = (request.form.get("message") or default_caption).strip()
    file_bytes = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "Fayl juda katta (20MB dan oshmasligi kerak)."}), 400
    mime_type = upload.mimetype or mimetypes.guess_type(upload.filename or "")[0] or "application/octet-stream"

    store = _load_store()
    conv = _resolve_conversation(store, request.form.get("conversation_id"))

    try:
        parts = [{"text": caption}, types.Part.from_bytes(data=file_bytes, mime_type=mime_type)]
        reply = _generate(conv, parts)
        _append_turn(store, conv, f"{caption} [{label}]", reply)
        return jsonify({"reply": reply, "conversation_id": conv["id"], "title": conv["title"]})
    except Exception as exc:
        return jsonify({"error": _friendly_error(exc)}), 500


@chat_bp.route("/image", methods=["POST"])
def chat_image():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    return _chat_with_file("image", "Bu rasmda nima bor? Tasvirlab ber.", "Rasm")


@chat_bp.route("/audio", methods=["POST"])
def chat_audio():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    return _chat_with_file("audio", "Bu audioda nima deyilmoqda? Javob ber.", "Audio")


@chat_bp.route("/file", methods=["POST"])
def chat_file():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    return _chat_with_file("file", "Bu faylni tahlil qilib ber.", "Fayl")
