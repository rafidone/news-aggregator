"""SQLite storage for digests and favorites.

Keeps a lightweight local database (news.db) that stores every digest the bot
sends plus the news items each user has favorited (keyed by Telegram chat id).
"""

import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.getenv(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.db"),
)
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dhaka"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS digests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    digest_date TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (chat_id, digest_date)
);

CREATE TABLE IF NOT EXISTS articles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id  INTEGER NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    title      TEXT NOT NULL,
    summary    TEXT,
    url        TEXT,
    source     TEXT
);

CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    summary    TEXT,
    url        TEXT,
    source     TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (chat_id, url)
);

CREATE INDEX IF NOT EXISTS idx_articles_digest ON articles(digest_id);
CREATE INDEX IF NOT EXISTS idx_favorites_chat ON favorites(chat_id);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path=DB_PATH):
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def now_iso():
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def today_str():
    return datetime.now(TIMEZONE).date().isoformat()


def save_digest(chat_id, digest_date, items, path=DB_PATH):
    """Insert/replace a digest and its articles. Returns the list of article ids."""
    with connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO digests (chat_id, digest_date, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT (chat_id, digest_date)
            DO UPDATE SET created_at = excluded.created_at
            """,
            (str(chat_id), digest_date, now_iso()),
        )
        digest_id = cur.lastrowid
        if not digest_id:
            digest_id = conn.execute(
                "SELECT id FROM digests WHERE chat_id = ? AND digest_date = ?",
                (str(chat_id), digest_date),
            ).fetchone()["id"]

        conn.execute("DELETE FROM articles WHERE digest_id = ?", (digest_id,))
        article_ids = []
        for pos, item in enumerate(items, 1):
            cur = conn.execute(
                """
                INSERT INTO articles (digest_id, position, title, summary, url, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    digest_id,
                    pos,
                    item.get("title", ""),
                    item.get("summary", ""),
                    item.get("url", ""),
                    item.get("source", ""),
                ),
            )
            article_ids.append(cur.lastrowid)
    return article_ids


def _row_to_item(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "url": row["url"],
        "source": row["source"],
    }


def get_digest(chat_id, digest_date, path=DB_PATH):
    """Return {date, items:[...]} for a specific date, or None."""
    with connect(path) as conn:
        digest = conn.execute(
            "SELECT * FROM digests WHERE chat_id = ? AND digest_date = ?",
            (str(chat_id), digest_date),
        ).fetchone()
        if not digest:
            return None
        rows = conn.execute(
            "SELECT * FROM articles WHERE digest_id = ? ORDER BY position",
            (digest["id"],),
        ).fetchall()
    return {"date": digest["digest_date"], "items": [_row_to_item(r) for r in rows]}


def get_latest_digest_before(chat_id, before_date, path=DB_PATH):
    """Return the most recent digest strictly before `before_date`, or None."""
    with connect(path) as conn:
        digest = conn.execute(
            """
            SELECT * FROM digests
            WHERE chat_id = ? AND digest_date < ?
            ORDER BY digest_date DESC LIMIT 1
            """,
            (str(chat_id), before_date),
        ).fetchone()
        if not digest:
            return None
        rows = conn.execute(
            "SELECT * FROM articles WHERE digest_id = ? ORDER BY position",
            (digest["id"],),
        ).fetchall()
    return {"date": digest["digest_date"], "items": [_row_to_item(r) for r in rows]}


def get_previous_digest(chat_id, path=DB_PATH):
    """Yesterday's digest if present, else the most recent one before today."""
    yesterday = (datetime.now(TIMEZONE).date() - timedelta(days=1)).isoformat()
    return get_digest(chat_id, yesterday, path) or get_latest_digest_before(
        chat_id, today_str(), path
    )


def get_article(article_id, path=DB_PATH):
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
    return _row_to_item(row) if row else None


def add_favorite(chat_id, item, path=DB_PATH):
    """Add an item to a user's favorites. Returns True if newly added."""
    with connect(path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO favorites (chat_id, title, summary, url, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(chat_id),
                    item.get("title", ""),
                    item.get("summary", ""),
                    item.get("url", ""),
                    item.get("source", ""),
                    now_iso(),
                ),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def list_favorites(chat_id, path=DB_PATH):
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM favorites WHERE chat_id = ? ORDER BY created_at DESC",
            (str(chat_id),),
        ).fetchall()
    return [_row_to_item(r) for r in rows]


def count_favorites(chat_id, path=DB_PATH):
    with connect(path) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM favorites WHERE chat_id = ?", (str(chat_id),)
        ).fetchone()["n"]
