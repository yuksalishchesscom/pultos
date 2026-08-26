"""PultOS relay-server.

Fleshkadagi klient(lar)ni va uy agentini bir-biriga bog'laydi. O'zi
buyruq bajarmaydi va Gemini kalitni bilmaydi -- faqat xabar yo'naltiradi
va Telegram ko'prigini ushlab turadi.

Ishga tushirish: python3 server.py
(avval 'python3 setup.py' orqali config.json yaratilgan bo'lishi kerak)
"""

import asyncio
import json
import logging

import websockets
from websockets.asyncio.server import serve

import config as relay_config
import social_db
from db import get_recent_messages, init_db, list_chats, store_message, upsert_chat
from telegram_bridge import TelegramBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pultos.relay")

agent_ws = None
clients = set()
telegram_bridge: TelegramBridge | None = None
_main_loop: asyncio.AbstractEventLoop | None = None

# PultOSgram: the free social layer shared by every flash-drive install.
# Kept separate from `clients` (the personal-relay set) -- social
# connections authenticate with their own per-user token, not relay_token.
social_clients: dict = {}


async def broadcast_to_clients(message: dict) -> None:
    if not clients:
        return
    raw = json.dumps(message)
    dead = []
    for ws in clients:
        try:
            await ws.send(raw)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def _broadcast_chats_list() -> None:
    await broadcast_to_clients({"type": "chats_list", "chats": list_chats()})


def _on_telegram_chat_seen(chat_id: str, title: str, chat_type: str) -> None:
    upsert_chat(chat_id, title, chat_type)


def _on_telegram_message(chat_id: str, title: str, chat_type: str, sender_name: str, text: str) -> None:
    # Called from telegram_bridge's poll loop, which runs _poll_once in a
    # worker thread (via asyncio.to_thread) -- must hop back onto _main_loop.
    msg = store_message(chat_id, sender_name, text)
    asyncio.run_coroutine_threadsafe(
        broadcast_to_clients({"type": "chat_message", **msg}),
        _main_loop,
    )
    asyncio.run_coroutine_threadsafe(_broadcast_chats_list(), _main_loop)


async def handle_agent(ws) -> None:
    global agent_ws
    if agent_ws is not None:
        try:
            await agent_ws.close()
        except Exception:
            pass
    agent_ws = ws
    logger.info("Uy agenti ulandi.")
    await broadcast_to_clients({"type": "status", "online": True})

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype in ("file_event", "command_result"):
                await broadcast_to_clients(msg)
    finally:
        if agent_ws is ws:
            agent_ws = None
            logger.info("Uy agenti uzildi.")
            await broadcast_to_clients({"type": "status", "online": False})


async def handle_client(ws) -> None:
    clients.add(ws)
    logger.info("Klient ulandi. Jami klientlar: %d", len(clients))
    try:
        await ws.send(json.dumps({"type": "status", "online": agent_ws is not None}))
        await ws.send(json.dumps({"type": "chats_list", "chats": list_chats()}))

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")

            if mtype == "get_chats":
                await ws.send(json.dumps({"type": "chats_list", "chats": list_chats()}))

            elif mtype == "get_messages":
                chat_id = msg.get("chat_id")
                await ws.send(
                    json.dumps(
                        {
                            "type": "messages_history",
                            "chat_id": chat_id,
                            "request_id": msg.get("request_id"),
                            "messages": get_recent_messages(chat_id) if chat_id else [],
                        }
                    )
                )

            elif mtype == "command":
                if agent_ws is None:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "command_result",
                                "request_id": msg.get("request_id"),
                                "error": "Uy kompyuteri oflayn.",
                            }
                        )
                    )
                else:
                    await agent_ws.send(raw)

            elif mtype == "send_message":
                chat_id = msg.get("chat_id")
                text = (msg.get("text") or "").strip()
                if chat_id and text:
                    own_msg = store_message(chat_id, "men", text)
                    if telegram_bridge is not None:
                        telegram_bridge.send_message(chat_id, text)
                    await broadcast_to_clients({"type": "chat_message", **own_msg})
                    await _broadcast_chats_list()
    finally:
        clients.discard(ws)
        logger.info("Klient uzildi. Jami klientlar: %d", len(clients))


async def _send_chats_to_user(user_id: int) -> None:
    ws = social_clients.get(user_id)
    if ws is None:
        return
    try:
        await ws.send(json.dumps({"type": "chats_list", "chats": social_db.list_chats_for_user(user_id)}))
    except Exception:
        pass


async def handle_social(ws, user_id: int, username: str) -> None:
    social_clients[user_id] = ws
    logger.info("PultOSgram: %s ulandi.", username)
    try:
        await ws.send(json.dumps({"type": "chats_list", "chats": social_db.list_chats_for_user(user_id)}))

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")

            if mtype == "get_chats":
                await ws.send(json.dumps({"type": "chats_list", "chats": social_db.list_chats_for_user(user_id)}))

            elif mtype == "get_messages":
                conversation_id = msg.get("conversation_id")
                messages = []
                if conversation_id and social_db.is_member(conversation_id, user_id):
                    for m in social_db.get_messages(conversation_id):
                        sender = "men" if m["sender_id"] == user_id else (social_db.get_username(m["sender_id"]) or "?")
                        messages.append({"from": sender, "text": m["text"], "ts": m["ts"]})
                await ws.send(
                    json.dumps(
                        {
                            "type": "messages_history",
                            "conversation_id": conversation_id,
                            "request_id": msg.get("request_id"),
                            "messages": messages,
                        }
                    )
                )

            elif mtype == "find_user":
                target = social_db.find_user((msg.get("username") or "").strip().lower())
                await ws.send(
                    json.dumps(
                        {
                            "type": "user_found",
                            "request_id": msg.get("request_id"),
                            "user": target,
                        }
                    )
                )

            elif mtype == "start_dm":
                target = social_db.find_user((msg.get("username") or "").strip().lower())
                if not target:
                    await ws.send(json.dumps({"type": "error", "request_id": msg.get("request_id"), "error": "Bunday foydalanuvchi topilmadi."}))
                    continue
                if target["user_id"] == user_id:
                    await ws.send(json.dumps({"type": "error", "request_id": msg.get("request_id"), "error": "O'zingizga yoza olmaysiz."}))
                    continue
                conversation_id = social_db.get_or_create_dm(user_id, target["user_id"])
                await ws.send(json.dumps({"type": "dm_started", "request_id": msg.get("request_id"), "conversation_id": conversation_id, "title": target["username"]}))
                await _send_chats_to_user(user_id)
                await _send_chats_to_user(target["user_id"])

            elif mtype == "create_group":
                name = (msg.get("name") or "").strip()
                usernames = [u.strip().lower() for u in msg.get("members", []) if u.strip()]
                if not name:
                    await ws.send(json.dumps({"type": "error", "request_id": msg.get("request_id"), "error": "Guruh nomini kiriting."}))
                    continue
                member_ids = []
                missing = []
                for uname in usernames:
                    found = social_db.find_user(uname)
                    if found:
                        member_ids.append(found["user_id"])
                    else:
                        missing.append(uname)
                if missing:
                    await ws.send(json.dumps({"type": "error", "request_id": msg.get("request_id"), "error": f"Topilmadi: {', '.join(missing)}"}))
                    continue
                conversation_id = social_db.create_group(name, user_id, member_ids)
                await ws.send(json.dumps({"type": "group_created", "request_id": msg.get("request_id"), "conversation_id": conversation_id}))
                for member_id in set(member_ids) | {user_id}:
                    await _send_chats_to_user(member_id)

            elif mtype == "send_message":
                conversation_id = msg.get("conversation_id")
                text = (msg.get("text") or "").strip()
                if not conversation_id or not text or not social_db.is_member(conversation_id, user_id):
                    continue
                own_msg = social_db.store_message(conversation_id, user_id, text)
                for member_id in social_db.conversation_members(conversation_id):
                    member_ws = social_clients.get(member_id)
                    if member_ws is None:
                        continue
                    sender_label = "men" if member_id == user_id else username
                    try:
                        await member_ws.send(
                            json.dumps(
                                {
                                    "type": "chat_message",
                                    "conversation_id": conversation_id,
                                    "from": sender_label,
                                    "text": own_msg["text"],
                                    "ts": own_msg["ts"],
                                }
                            )
                        )
                    except Exception:
                        pass
                for member_id in social_db.conversation_members(conversation_id):
                    await _send_chats_to_user(member_id)
    finally:
        if social_clients.get(user_id) is ws:
            del social_clients[user_id]
        logger.info("PultOSgram: %s uzildi.", username)


async def handler(ws) -> None:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(code=1008, reason="hello kutildi")
        return

    if hello.get("type") != "hello":
        await ws.close(code=1008, reason="ruxsat yo'q")
        return

    role = hello.get("role")

    if role == "social":
        username = (hello.get("username") or "").strip().lower()
        token = hello.get("token") or ""
        if not username or not token:
            await ws.close(code=1008, reason="ruxsat yo'q")
            return
        if hello.get("action") == "register":
            user = social_db.register_user(username, token)
            if user is None:
                await ws.send(json.dumps({"type": "register_result", "ok": False, "error": "Bu username band."}))
                await ws.close()
                return
            await ws.send(json.dumps({"type": "register_result", "ok": True, "username": username}))
            await handle_social(ws, user["user_id"], username)
            return
        user = social_db.authenticate(username, token)
        if user is None:
            await ws.close(code=1008, reason="ruxsat yo'q")
            return
        await handle_social(ws, user["user_id"], username)
        return

    if hello.get("token") != relay_config.load()["relay_token"]:
        await ws.close(code=1008, reason="ruxsat yo'q")
        return

    if role == "agent":
        await handle_agent(ws)
    elif role == "client":
        await handle_client(ws)
    else:
        await ws.close(code=1008, reason="notanish rol")


def _backfill_legacy_chat_title(bot_token: str) -> None:
    """One-time nicety: the pre-multi-chat DB migration seeds a 'legacy'
    chat with a placeholder title. If the old single-chat config still
    names a real chat_id, ask Telegram for its real title so the migrated
    conversation shows up correctly labeled instead of 'Oldingi suhbat'."""
    old_chat_id = relay_config.load().get("telegram_allowed_chat_id")
    if not old_chat_id:
        return
    bridge = TelegramBridge(bot_token=bot_token, on_message=lambda *a: None)
    info = bridge.fetch_chat(old_chat_id)
    if info:
        upsert_chat(str(old_chat_id), info["title"], info["type"])


async def main() -> None:
    global telegram_bridge, _main_loop
    _main_loop = asyncio.get_running_loop()
    init_db()
    social_db.init_db()
    cfg = relay_config.load()

    if cfg.get("telegram_bot_token"):
        _backfill_legacy_chat_title(cfg["telegram_bot_token"])
        telegram_bridge = TelegramBridge(
            bot_token=cfg["telegram_bot_token"],
            on_message=_on_telegram_message,
            on_chat_seen=_on_telegram_chat_seen,
        )
        asyncio.create_task(telegram_bridge.run_forever())
    else:
        logger.warning("telegram_bot_token sozlanmagan -- Xabarlar bo'limi ishlamaydi.")

    async with serve(handler, cfg["host"], cfg["port"]):
        logger.info("Relay ishga tushdi: %s:%s", cfg["host"], cfg["port"])
        await asyncio.Future()  # abadiy kutish


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
