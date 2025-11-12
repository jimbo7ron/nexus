from __future__ import annotations

import aiosqlite
from pathlib import Path
from typing import Optional


DB_PATH = Path("/Users/jammor/Developer/nexus/db/queue.sqlite")
_db_connection: Optional[aiosqlite.Connection] = None


async def _ensure_db(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_hashes (
            url TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.commit()


async def get_conn() -> aiosqlite.Connection:
    """Get or create a single shared database connection."""
    global _db_connection

    if _db_connection is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db_connection = await aiosqlite.connect(DB_PATH)
        # Enable WAL mode for better concurrent access
        await _db_connection.execute("PRAGMA journal_mode=WAL")
        await _ensure_db(_db_connection)

    return _db_connection


async def close_db():
    """Close the shared database connection."""
    global _db_connection
    if _db_connection:
        await _db_connection.close()
        _db_connection = None


async def get_stored_hash(url: str) -> Optional[str]:
    conn = await get_conn()
    async with conn.execute("SELECT content_hash FROM seen_hashes WHERE url = ?", (url,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else None


async def has_changed(url: str, new_hash: str) -> bool:
    old = await get_stored_hash(url)
    return old != new_hash


async def mark_processed(url: str, content_hash: str) -> None:
    conn = await get_conn()
    await conn.execute(
        "INSERT INTO seen_hashes(url, content_hash) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET content_hash=excluded.content_hash, updated_at=CURRENT_TIMESTAMP",
        (url, content_hash),
    )
    await conn.commit()
