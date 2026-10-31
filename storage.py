import sqlite3
import time
from contextlib import contextmanager

import config

# סטטוסים: posted, skipped, pending, rejected, failed -> "טופל" | retry -> ינסה שוב
DONE = ("posted", "skipped", "pending", "rejected", "failed")


@contextmanager
def _conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS articles(
                id TEXT PRIMARY KEY, url TEXT, title TEXT, status TEXT,
                attempts INTEGER DEFAULT 0, draft TEXT,
                created_at REAL, updated_at REAL)"""
        )
        # מנקה רשומות ישנות מעל 14 יום
        c.execute("DELETE FROM articles WHERE updated_at < ?", (time.time() - 14 * 86400,))


def is_done(article_id):
    with _conn() as c:
        row = c.execute("SELECT status FROM articles WHERE id=?", (article_id,)).fetchone()
    return bool(row and row["status"] in DONE)


def attempts(article_id):
    with _conn() as c:
        row = c.execute("SELECT attempts FROM articles WHERE id=?", (article_id,)).fetchone()
    return row["attempts"] if row else 0


def mark(article_id, status, url="", title="", draft=None, attempts=0):
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO articles(id,url,title,status,attempts,draft,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, attempts=excluded.attempts,
                 draft=COALESCE(excluded.draft, articles.draft), updated_at=excluded.updated_at""",
            (article_id, url, title, status, attempts, draft, now, now),
        )


def set_status(article_id, status):
    with _conn() as c:
        c.execute("UPDATE articles SET status=?, updated_at=? WHERE id=?", (status, time.time(), article_id))


def get(article_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    return dict(row) if row else None


def recent_titles(limit=200):
    with _conn() as c:
        rows = c.execute(
            "SELECT title FROM articles WHERE status IN ('posted','pending') ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r["title"] for r in rows if r["title"]]
