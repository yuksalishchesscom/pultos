from flask import Blueprint, jsonify, request, session

from . import relay_client, runtime

messages_bp = Blueprint("messages", __name__, url_prefix="/api/messages")


def _require_auth() -> bool:
    return session.get("authed") is True


@messages_bp.route("/chats", methods=["GET"])
def list_chats():
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    if not runtime.get("relay_url"):
        return jsonify({"configured": False, "chats": []})
    return jsonify({"configured": True, "chats": relay_client.get_chats()})


@messages_bp.route("/<chat_id>", methods=["GET"])
def list_messages(chat_id):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    if not runtime.get("relay_url"):
        return jsonify({"configured": False, "messages": []})
    return jsonify({"configured": True, "messages": relay_client.fetch_chat_messages(chat_id)})


@messages_bp.route("/<chat_id>/send", methods=["POST"])
def send_message(chat_id):
    if not _require_auth():
        return jsonify({"error": "Avval tizimga kiring."}), 401
    if not runtime.get("relay_url"):
        return jsonify({"error": "Xabarlar bo'limi hali sozlanmagan."}), 400

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Xabar boʻsh boʻlishi mumkin emas."}), 400

    if not relay_client.send_chat_message(chat_id, text):
        return jsonify({"error": "Yuborib boʻlmadi (aloqa yoʻq)."}), 502

    return jsonify({"ok": True})
