import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.db")


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            chat_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            last_ts REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            text TEXT NOT NULL,
            ts REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_offset (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            offset INTEGER NOT NULL
        )
        """
    )
    conn.commit()

    # Migration from the pre-multi-chat schema: old `messages` rows have no
    # chat_id column. If we find one, backfill every row into a single
    # legacy chat so existing history is not lost.
    cols = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "chat_id" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN chat_id TEXT")
        conn.execute("UPDATE messages SET chat_id = 'legacy' WHERE chat_id IS NULL")
        row = conn.execute("SELECT MAX(ts) FROM messages WHERE chat_id = 'legacy'").fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO chats (chat_id, title, type, last_ts) VALUES ('legacy', 'Oldingi suhbat', 'private', ?)",
            (row[0] or time.time(),),
        )
        conn.commit()
    conn.close()


def upsert_chat(chat_id: str, title: str, chat_type: str, ts: float | None = None) -> None:
    ts = ts if ts is not None else time.time()
    conn = _connect()
    conn.execute(
        """
        INSERT INTO chats (chat_id, title, type, last_ts) VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, type = excluded.type, last_ts = excluded.last_ts
        """,
        (chat_id, title, chat_type, ts),
    )
    conn.commit()
    conn.close()


def touch_chat(chat_id: str, ts: float | None = None) -> None:
    ts = ts if ts is not None else time.time()
    conn = _connect()
    conn.execute("UPDATE chats SET last_ts = ? WHERE chat_id = ?", (ts, chat_id))
    conn.commit()
    conn.close()


def list_chats() -> list:
    conn = _connect()
    rows = conn.execute(
        """
        SELECT c.chat_id, c.title, c.type, c.last_ts,
               (SELECT text FROM messages m WHERE m.chat_id = c.chat_id ORDER BY m.id DESC LIMIT 1)
        FROM chats c ORDER BY c.last_ts DESC
        """
    ).fetchall()
    conn.close()
    return [
        {"chat_id": r[0], "title": r[1], "type": r[2], "last_ts": r[3], "preview": r[4] or ""}
        for r in rows
    ]


def store_message(chat_id: str, sender: str, text: str) -> dict:
    ts = time.time()
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (chat_id, sender, text, ts) VALUES (?, ?, ?, ?)", (chat_id, sender, text, ts)
    )
    conn.execute("UPDATE chats SET last_ts = ? WHERE chat_id = ?", (ts, chat_id))
    conn.commit()
    conn.close()
    return {"chat_id": chat_id, "from": sender, "text": text, "ts": ts}


def get_recent_messages(chat_id: str, limit: int = 200) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT sender, text, ts FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)
    ).fetchall()
    conn.close()
    return [{"from": r[0], "text": r[1], "ts": r[2]} for r in reversed(rows)]


def get_telegram_offset() -> int:
    conn = _connect()
    row = conn.execute("SELECT offset FROM telegram_offset WHERE id = 1").fetchone()
    conn.close()
    return row[0] if row else 0


def set_telegram_offset(offset: int) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO telegram_offset (id, offset) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET offset = excluded.offset",
        (offset,),
    )
    conn.commit()
    conn.close()
