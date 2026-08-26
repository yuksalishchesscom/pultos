"""SQLite storage for PultOSgram -- the free social layer shared by every
PultOS flash-drive install (separate from the personal home-agent relay and
the per-install Telegram bridge, both of which stay single-tenant)."""

import hashlib
import os
import sqlite3
import time
import uuid

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social.db")


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            token_hash TEXT NOT NULL,
            created_ts REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT,
            last_ts REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_members (
            conversation_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (conversation_id, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            ts REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_user(username: str, token: str) -> dict | None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users (username, token_hash, created_ts) VALUES (?, ?, ?)",
            (username, hash_token(token), time.time()),
        )
        conn.commit()
        user_id = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()[0]
        return {"user_id": user_id, "username": username}
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def authenticate(username: str, token: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT user_id, token_hash FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row and row[1] == hash_token(token):
        return {"user_id": row[0], "username": username}
    return None


def find_user(username: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT user_id, username FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return {"user_id": row[0], "username": row[1]} if row else None


def get_username(user_id: int) -> str | None:
    conn = _connect()
    row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_or_create_dm(user_a: int, user_b: int) -> str:
    lo, hi = sorted([user_a, user_b])
    conversation_id = f"dm:{lo}:{hi}"
    conn = _connect()
    conn.execute(
        "INSERT OR IGNORE INTO conversations (conversation_id, type, title, last_ts) VALUES (?, 'dm', NULL, ?)",
        (conversation_id, time.time()),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?, ?)",
        [(conversation_id, user_a), (conversation_id, user_b)],
    )
    conn.commit()
    conn.close()
    return conversation_id


def create_group(name: str, owner_id: int, member_ids: list) -> str:
    conversation_id = f"grp:{uuid.uuid4().hex}"
    conn = _connect()
    conn.execute(
        "INSERT INTO conversations (conversation_id, type, title, last_ts) VALUES (?, 'group', ?, ?)",
        (conversation_id, name, time.time()),
    )
    all_members = set(member_ids) | {owner_id}
    conn.executemany(
        "INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?, ?)",
        [(conversation_id, uid) for uid in all_members],
    )
    conn.commit()
    conn.close()
    return conversation_id


def is_member(conversation_id: str, user_id: int) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM conversation_members WHERE conversation_id = ? AND user_id = ?", (conversation_id, user_id)
    ).fetchone()
    conn.close()
    return row is not None


def conversation_members(conversation_id: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = ?", (conversation_id,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def conversation_type(conversation_id: str) -> str | None:
    conn = _connect()
    row = conn.execute("SELECT type FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def store_message(conversation_id: str, sender_id: int, text: str) -> dict:
    ts = time.time()
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (conversation_id, sender_id, text, ts) VALUES (?, ?, ?, ?)",
        (conversation_id, sender_id, text, ts),
    )
    conn.execute("UPDATE conversations SET last_ts = ? WHERE conversation_id = ?", (ts, conversation_id))
    conn.commit()
    conn.close()
    return {"conversation_id": conversation_id, "sender_id": sender_id, "text": text, "ts": ts}


def get_messages(conversation_id: str, limit: int = 200) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT sender_id, text, ts FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    return [{"sender_id": r[0], "text": r[1], "ts": r[2]} for r in reversed(rows)]


def list_chats_for_user(user_id: int) -> list:
    conn = _connect()
    rows = conn.execute(
        """
        SELECT c.conversation_id, c.type, c.title, c.last_ts,
               (SELECT text FROM messages m WHERE m.conversation_id = c.conversation_id ORDER BY m.id DESC LIMIT 1)
        FROM conversations c
        JOIN conversation_members cm ON cm.conversation_id = c.conversation_id
        WHERE cm.user_id = ?
        ORDER BY c.last_ts DESC
        """,
        (user_id,),
    ).fetchall()

    chats = []
    for conversation_id, ctype, title, last_ts, preview in rows:
        if ctype == "dm":
            other = conn.execute(
                "SELECT user_id FROM conversation_members WHERE conversation_id = ? AND user_id != ?",
                (conversation_id, user_id),
            ).fetchone()
            other_username = None
            if other:
                urow = conn.execute("SELECT username FROM users WHERE user_id = ?", (other[0],)).fetchone()
                other_username = urow[0] if urow else None
            title = other_username or "Noma'lum"
        chats.append(
            {"chat_id": conversation_id, "title": title, "type": ctype, "last_ts": last_ts, "preview": preview or ""}
        )
    conn.close()
    return chats
