from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


DB_PATH = Path("/Users/jammor/Developer/nexus/db/queue.sqlite")


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_hashes (
            url TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _ensure_db(conn)
    return conn


def get_stored_hash(url: str) -> Optional[str]:
    with get_conn() as conn:
        cur = conn.execute("SELECT content_hash FROM seen_hashes WHERE url = ?", (url,))
        row = cur.fetchone()
        return row[0] if row else None


def has_changed(url: str, new_hash: str) -> bool:
    old = get_stored_hash(url)
    return old != new_hash


def mark_processed(url: str, content_hash: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO seen_hashes(url, content_hash) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET content_hash=excluded.content_hash, updated_at=CURRENT_TIMESTAMP",
            (url, content_hash),
        )
        conn.commit()


