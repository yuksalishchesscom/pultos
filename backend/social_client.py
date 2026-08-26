"""Persistent WebSocket connection to the shared PultOSgram social server.

Runs its own asyncio loop in a background thread, independent of the
personal home-agent relay connection (relay_client.py): different role,
different per-user credentials, but always the same shared server address
so PultOSgram works out of the box on any copy of the flash drive without
per-install setup.
"""

import asyncio
import json
import queue
import threading
import time
import uuid

import websockets

SOCIAL_SERVER_URL = "wss://35.202.98.120.sslip.io"
MAX_CHAT_MESSAGES = 200

_state = {"connected": False, "chats": [], "messages_by_chat": {}, "username": None}
_pending_message_requests = {}
_pending_action_requests = {}
_subscribers = []
_lock = threading.Lock()

_loop = None
_thread = None
_ws = None
_stop_flag = threading.Event()
_credentials = {"username": None, "token": None}


def _broadcast(event: dict) -> None:
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except Exception:
            pass


def subscribe() -> "queue.Queue":
    q = queue.Queue()
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q) -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def is_connected() -> bool:
    return _state["connected"]


def get_username():
    return _state["username"]


def get_chats() -> list:
    with _lock:
        return list(_state["chats"])


def get_cached_messages(conversation_id: str) -> list:
    with _lock:
        return list(_state["messages_by_chat"].get(conversation_id, []))


def _set_connected(connected: bool) -> None:
    with _lock:
        _state["connected"] = connected
    _broadcast({"type": "social_status", "connected": connected})


async def _handle_incoming(msg: dict) -> None:
    mtype = msg.get("type")
    if mtype == "chats_list":
        with _lock:
            _state["chats"] = list(msg.get("chats", []))
        _broadcast({"type": "social_chats_list", "chats": _state["chats"]})
    elif mtype == "chat_message":
        conversation_id = msg.get("conversation_id")
        if conversation_id:
            entry = {"from": msg.get("from", ""), "text": msg.get("text", ""), "ts": msg.get("ts", time.time())}
            with _lock:
                bucket = _state["messages_by_chat"].setdefault(conversation_id, [])
                bucket.append(entry)
                _state["messages_by_chat"][conversation_id] = bucket[-MAX_CHAT_MESSAGES:]
            _broadcast({"type": "social_chat_message", "conversation_id": conversation_id, **entry})
    elif mtype == "messages_history":
        conversation_id = msg.get("conversation_id")
        messages = list(msg.get("messages", []))
        if conversation_id:
            with _lock:
                _state["messages_by_chat"][conversation_id] = messages[-MAX_CHAT_MESSAGES:]
        req_id = msg.get("request_id")
        with _lock:
            fut = _pending_message_requests.pop(req_id, None) if req_id else None
        if fut is not None and not fut.done():
            fut.set_result(messages)
    elif mtype in ("user_found", "dm_started", "group_created", "error"):
        req_id = msg.get("request_id")
        with _lock:
            fut = _pending_action_requests.pop(req_id, None) if req_id else None
        if fut is not None and not fut.done():
            fut.set_result(msg)


async def _ws_loop() -> None:
    global _ws
    backoff = 2
    while not _stop_flag.is_set():
        try:
            async with websockets.connect(SOCIAL_SERVER_URL, open_timeout=10) as ws:
                _ws = ws
                await ws.send(
                    json.dumps(
                        {
                            "type": "hello",
                            "role": "social",
                            "action": "login",
                            "username": _credentials["username"],
                            "token": _credentials["token"],
                        }
                    )
                )
                _set_connected(True)
                backoff = 2
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await _handle_incoming(msg)
        except Exception:
            pass
        finally:
            _ws = None
            _set_connected(False)
        if _stop_flag.is_set():
            break
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


def _run_loop() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_ws_loop())


def ensure_started(username: str, token: str) -> None:
    global _thread
    _credentials["username"] = username
    _credentials["token"] = token
    _state["username"] = username
    if _thread is not None and _thread.is_alive():
        return
    _stop_flag.clear()
    _thread = threading.Thread(target=_run_loop, daemon=True)
    _thread.start()


def stop() -> None:
    _stop_flag.set()
    if _loop is not None:
        try:
            _loop.call_soon_threadsafe(_loop.stop)
        except Exception:
            pass


def register(username: str, token: str, timeout: float = 10.0) -> dict:
    """One-off registration: connects once, sends a register hello, waits
    for the result. On success also starts the persistent connection."""
    result = {}
    done = threading.Event()

    async def _do():
        try:
            async with websockets.connect(SOCIAL_SERVER_URL, open_timeout=10) as ws:
                await ws.send(
                    json.dumps({"type": "hello", "role": "social", "action": "register", "username": username, "token": token})
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                result.update(json.loads(raw))
        except Exception:
            result["ok"] = False
            result["error"] = "Serverga ulanib bo'lmadi."
        done.set()

    threading.Thread(target=lambda: asyncio.run(_do()), daemon=True).start()
    done.wait(timeout + 2)
    if result.get("ok"):
        ensure_started(username, token)
    return result


async def _await_action(request_id: str, payload: dict):
    fut = asyncio.get_event_loop().create_future()
    with _lock:
        _pending_action_requests[request_id] = fut
    await _ws.send(json.dumps(payload))
    return await fut


def _run_action(action_payload: dict, timeout: float = 10.0) -> dict:
    if _loop is None or _ws is None:
        return {"error": "PultOSgram bilan aloqa yo'q."}
    request_id = uuid.uuid4().hex
    payload = {**action_payload, "request_id": request_id}
    fut = asyncio.run_coroutine_threadsafe(_await_action(request_id, payload), _loop)
    try:
        return fut.result(timeout=timeout)
    except Exception:
        return {"error": "Vaqt tugadi yoki aloqa uzildi."}


def find_user(username: str) -> dict:
    return _run_action({"type": "find_user", "username": username})


def start_dm(username: str) -> dict:
    return _run_action({"type": "start_dm", "username": username})


def create_group(name: str, members: list) -> dict:
    return _run_action({"type": "create_group", "name": name, "members": members})


def fetch_chat_messages(conversation_id: str, timeout: float = 10.0) -> list:
    if _loop is None or _ws is None:
        return get_cached_messages(conversation_id)

    async def _await_msgs(request_id: str):
        fut = asyncio.get_event_loop().create_future()
        with _lock:
            _pending_message_requests[request_id] = fut
        await _ws.send(json.dumps({"type": "get_messages", "conversation_id": conversation_id, "request_id": request_id}))
        return await fut

    request_id = uuid.uuid4().hex
    fut = asyncio.run_coroutine_threadsafe(_await_msgs(request_id), _loop)
    try:
        return fut.result(timeout=timeout)
    except Exception:
        return get_cached_messages(conversation_id)


def send_message(conversation_id: str, text: str) -> bool:
    if _loop is None or _ws is None:
        return False

    async def _send():
        await _ws.send(json.dumps({"type": "send_message", "conversation_id": conversation_id, "text": text}))

    fut = asyncio.run_coroutine_threadsafe(_send(), _loop)
    try:
        fut.result(timeout=5)
        return True
    except Exception:
        return False
