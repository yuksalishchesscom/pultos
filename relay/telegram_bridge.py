"""Minimal Telegram Bot API bridge: long-polling for inbound messages,
plain REST call for outbound ones. No extra dependency beyond `requests`.

Accepts messages from any chat the bot has been added to (private chats or
groups) instead of a single hardcoded chat -- callers get a chat_id/title/
type per message and can fan them out into separate conversations.
"""

import asyncio
import logging

import requests

from db import get_telegram_offset, set_telegram_offset

logger = logging.getLogger("pultos.telegram")

API_BASE = "https://api.telegram.org/bot{token}"


def _chat_title(chat: dict) -> str:
    if chat.get("title"):
        return chat["title"]
    name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])).strip()
    return name or chat.get("username") or "Noma'lum"


class TelegramBridge:
    def __init__(self, bot_token: str, on_message, on_chat_seen=None):
        self._base = API_BASE.format(token=bot_token)
        self._on_message = on_message  # sync callback(chat_id, title, type, sender_name, text)
        self._on_chat_seen = on_chat_seen  # sync callback(chat_id, title, type) -> None

    def send_message(self, chat_id: str, text: str) -> bool:
        try:
            resp = requests.post(
                f"{self._base}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=15,
            )
            return resp.status_code == 200
        except requests.RequestException:
            logger.exception("Telegram sendMessage xatoligi")
            return False

    def fetch_chat(self, chat_id: str) -> dict | None:
        try:
            resp = requests.get(f"{self._base}/getChat", params={"chat_id": chat_id}, timeout=15)
            resp.raise_for_status()
            result = resp.json().get("result") or {}
            return {"title": _chat_title(result), "type": result.get("type", "private")}
        except requests.RequestException:
            logger.exception("Telegram getChat xatoligi")
            return None

    def _poll_once(self) -> None:
        offset = get_telegram_offset()
        try:
            resp = requests.get(
                f"{self._base}/getUpdates",
                params={"timeout": 25, "offset": offset + 1},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("Telegram getUpdates xatoligi")
            return

        data = resp.json()
        for update in data.get("result", []):
            offset = max(offset, update["update_id"])
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id", ""))
            text = message.get("text")
            if not chat_id or not text:
                continue

            title = _chat_title(chat)
            chat_type = chat.get("type", "private")
            if self._on_chat_seen:
                self._on_chat_seen(chat_id, title, chat_type)

            from_user = message.get("from") or {}
            sender_name = _chat_title(from_user) if from_user else title
            self._on_message(chat_id, title, chat_type, sender_name, text)

        set_telegram_offset(offset)

    async def run_forever(self) -> None:
        while True:
            await asyncio.to_thread(self._poll_once)
