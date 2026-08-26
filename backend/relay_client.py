"""Persistent WebSocket connection to the relay server.

Runs its own asyncio event loop in a background thread (Flask itself stays
sync). Flask request handlers talk to this module through plain function
calls; cross-thread scheduling onto the event loop uses
asyncio.run_coroutine_threadsafe.
"""

import asyncio
import json
import queue
import threading
import time
import uuid

import websockets

from . import runtime

MAX_FILE_EVENTS = 100
MAX_CHAT_MESSAGES = 200

_state = {"online": False, "last_seen": None, "file_events": [], "chats": [], "messages_by_chat": {}}
_pending_commands = {}
_pending_message_requests = {}
_subscribers = []
_lock = threading.Lock()

_loop = None
_thread = None
_ws = None
_stop_flag = threading.Event()


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


def get_state() -> dict:
    with _lock:
        return {
            "online": _state["online"],
            "last_seen": _state["last_seen"],
            "file_events": list(_state["file_events"][-50:]),
        }


def get_chats() -> list:
    with _lock:
        return list(_state["chats"])


def get_cached_messages(chat_id: str) -> list:
    with _lock:
        return list(_state["messages_by_chat"].get(chat_id, []))


def _record_file_event(msg: dict) -> None:
    with _lock:
        _state["file_events"].append(msg)
        _state["file_events"] = _state["file_events"][-MAX_FILE_EVENTS:]
    _broadcast({"type": "file_event", **msg})


def _record_chat_message(chat_id: str, msg: dict) -> None:
    with _lock:
        bucket = _state["messages_by_chat"].setdefault(chat_id, [])
        bucket.append(msg)
        _state["messages_by_chat"][chat_id] = bucket[-MAX_CHAT_MESSAGES:]
    _broadcast({"type": "chat_message", "chat_id": chat_id, **msg})


def _set_online(online: bool) -> None:
    with _lock:
        _state["online"] = online
        _state["last_seen"] = time.time()
    _broadcast({"type": "status", "online": online})


async def _handle_incoming(msg: dict) -> None:
    mtype = msg.get("type")
    if mtype == "status":
        _set_online(bool(msg.get("online")))
    elif mtype == "file_event":
        _record_file_event(
            {"path": msg.get("path"), "event": msg.get("event"), "ts": msg.get("ts", time.time())}
        )
    elif mtype == "command_result":
        req_id = msg.get("request_id")
        with _lock:
            fut = _pending_commands.pop(req_id, None)
        if fut is not None and not fut.done():
            fut.set_result(msg)
    elif mtype == "chat_message":
        chat_id = msg.get("chat_id")
        if chat_id:
            _record_chat_message(chat_id, {"from": msg.get("from", ""), "text": msg.get("text", ""), "ts": msg.get("ts", time.time())})
    elif mtype == "chats_list":
        with _lock:
            _state["chats"] = list(msg.get("chats", []))
        _broadcast({"type": "chats_list", "chats": _state["chats"]})
    elif mtype == "messages_history":
        chat_id = msg.get("chat_id")
        messages = list(msg.get("messages", []))
        if chat_id:
            with _lock:
                _state["messages_by_chat"][chat_id] = messages[-MAX_CHAT_MESSAGES:]
        req_id = msg.get("request_id")
        with _lock:
            fut = _pending_message_requests.pop(req_id, None) if req_id else None
        if fut is not None and not fut.done():
            fut.set_result(messages)


async def _ws_loop() -> None:
    global _ws
    backoff = 2
    while not _stop_flag.is_set():
        try:
            async with websockets.connect(runtime["relay_url"], open_timeout=10) as ws:
                _ws = ws
                await ws.send(json.dumps({"type": "hello", "role": "client", "token": runtime["relay_token"]}))
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
            _set_online(False)
        if _stop_flag.is_set():
            break
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


def _run_loop() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_ws_loop())


def ensure_started() -> None:
    global _thread
    if not runtime.get("relay_url") or not runtime.get("relay_token"):
        return
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


async def _await_command(request_id: str, action: str, payload: dict):
    fut = asyncio.get_event_loop().create_future()
    with _lock:
        _pending_commands[request_id] = fut
    await _ws.send(
        json.dumps(
            {
                "type": "command",
                "request_id": request_id,
                "agent_secret": runtime["agent_secret"],
                "action": action,
                "payload": payload,
            }
        )
    )
    return await fut


def send_command(action: str, payload: dict, timeout: float = 15.0) -> dict:
    if _loop is None or _ws is None:
        return {"error": "Uy kompyuteri bilan aloqa yoʻq (oflayn)."}

    request_id = uuid.uuid4().hex
    fut = asyncio.run_coroutine_threadsafe(_await_command(request_id, action, payload), _loop)
    try:
        return fut.result(timeout=timeout)
    except Exception:
        return {"error": "Buyruq vaqti tugadi yoki aloqa uzildi."}


async def _await_messages(request_id: str, chat_id: str):
    fut = asyncio.get_event_loop().create_future()
    with _lock:
        _pending_message_requests[request_id] = fut
    await _ws.send(json.dumps({"type": "get_messages", "chat_id": chat_id, "request_id": request_id}))
    return await fut


def fetch_chat_messages(chat_id: str, timeout: float = 10.0) -> list:
    if _loop is None or _ws is None:
        return get_cached_messages(chat_id)

    request_id = uuid.uuid4().hex
    fut = asyncio.run_coroutine_threadsafe(_await_messages(request_id, chat_id), _loop)
    try:
        return fut.result(timeout=timeout)
    except Exception:
        return get_cached_messages(chat_id)


def send_chat_message(chat_id: str, text: str) -> bool:
    if _loop is None or _ws is None:
        return False

    async def _send():
        await _ws.send(json.dumps({"type": "send_message", "chat_id": chat_id, "text": text}))

    fut = asyncio.run_coroutine_threadsafe(_send(), _loop)
    try:
        fut.result(timeout=5)
        return True
    except Exception:
        return False
