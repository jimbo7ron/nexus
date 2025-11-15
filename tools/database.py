"""SQLite database abstraction layer for content storage.

This module provides async database operations for storing videos, articles,
and ingestion logs. It replaces the Notion backend with a local SQLite database.
"""

from __future__ import annotations

import asyncio
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

# Database file location
DB_PATH = Path(__file__).parent.parent / "db" / "nexus.sqlite"


class DatabaseWriter:
    """Async database writer for content storage.

    This class provides the same interface as NotionWriter but uses SQLite
    instead of the Notion API. All methods are async to maintain compatibility
    with the existing ingestion pipeline.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database writer.

        Args:
            db_path: Optional custom database path (defaults to db/nexus.sqlite)
        """
        self.db_path = db_path or DB_PATH
        self._conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def connect(self):
        """Establish database connection and ensure schema exists."""
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect with WAL mode for better concurrency
        self._conn = await aiosqlite.connect(str(self.db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Create tables if they don't exist
        await self._create_tables()

    async def close(self):
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _create_tables(self):
        """Create database schema if it doesn't exist."""

        # Videos table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                thumbnail_url TEXT,
                summary TEXT,
                source TEXT,
                published_at TEXT,
                last_updated_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                CONSTRAINT url_not_empty CHECK (length(url) > 0)
            )
        """)

        # Videos indexes
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_url ON videos(url)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_updated ON videos(updated_at DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_source ON videos(source)"
        )

        # Videos full-text search
        await self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
                title, summary,
                content=videos,
                content_rowid=id
            )
        """)

        # Articles table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                summary TEXT,
                body TEXT,
                source TEXT,
                published_at TEXT,
                last_updated_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                CONSTRAINT url_not_empty CHECK (length(url) > 0)
            )
        """)

        # Articles indexes
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_updated ON articles(updated_at DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source)"
        )

        # Articles full-text search
        await self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                title, summary, body,
                content=articles,
                content_rowid=id
            )
        """)

        # Ingestion logs table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL DEFAULT (datetime('now')),
                item_url TEXT NOT NULL,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                message TEXT,
                CONSTRAINT action_valid CHECK (action IN ('discover', 'fetch', 'summarize', 'write')),
                CONSTRAINT result_valid CHECK (result IN ('ok', 'skip', 'error'))
            )
        """)

        # Logs indexes
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_logs_time ON ingestion_logs(time DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_logs_url ON ingestion_logs(item_url)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_logs_action_result ON ingestion_logs(action, result)"
        )

        await self._conn.commit()

    async def upsert_video(
        self,
        title: str,
        url: str,
        summary: str = "",
        thumbnail: str = "",
        source: str = "",
        published_iso: Optional[str] = None,
        last_updated_iso: Optional[str] = None,
    ) -> str:
        """Insert or update a video in the database.

        Args:
            title: Video title
            url: Video URL (unique key)
            summary: LLM-generated summary
            thumbnail: Thumbnail image URL
            source: Channel name
            published_iso: ISO 8601 publish date
            last_updated_iso: ISO 8601 last update date

        Returns:
            Row ID as string (for NotionWriter compatibility)
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = await self._conn.execute("""
            INSERT INTO videos (url, title, thumbnail_url, summary, source, published_at, last_updated_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                thumbnail_url = excluded.thumbnail_url,
                summary = excluded.summary,
                source = excluded.source,
                published_at = excluded.published_at,
                last_updated_at = excluded.last_updated_at,
                updated_at = excluded.updated_at
            RETURNING id
        """, (url, title, thumbnail, summary, source, published_iso, last_updated_iso, now))

        row = await cursor.fetchone()
        await self._conn.commit()
        return str(row[0])

    async def upsert_article(
        self,
        title: str,
        url: str,
        summary: str = "",
        body: str = "",
        source: str = "",
        published_iso: Optional[str] = None,
        last_updated_iso: Optional[str] = None,
    ) -> str:
        """Insert or update an article in the database.

        Args:
            title: Article title
            url: Article URL (unique key)
            summary: LLM-generated summary
            body: Full article text
            source: Site name or "Hacker News (XXX points)"
            published_iso: ISO 8601 publish date
            last_updated_iso: ISO 8601 last update date

        Returns:
            Row ID as string (for NotionWriter compatibility)
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = await self._conn.execute("""
            INSERT INTO articles (url, title, summary, body, source, published_at, last_updated_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                body = excluded.body,
                source = excluded.source,
                published_at = excluded.published_at,
                last_updated_at = excluded.last_updated_at,
                updated_at = excluded.updated_at
            RETURNING id
        """, (url, title, summary, body, source, published_iso, last_updated_iso, now))

        row = await cursor.fetchone()
        await self._conn.commit()
        return str(row[0])

    async def log_event(
        self,
        item_url: str,
        action: str,
        result: str,
        message: str = "",
        when_iso: Optional[str] = None,
    ) -> str:
        """Log an ingestion event.

        Args:
            item_url: URL of the item being processed
            action: Action type (discover, fetch, summarize, write)
            result: Result status (ok, skip, error)
            message: Optional details or error message
            when_iso: ISO 8601 timestamp (auto-generated if not provided)

        Returns:
            Row ID as string (for NotionWriter compatibility)
        """
        # Auto-generate timestamp if not provided
        if not when_iso:
            when_iso = datetime.now(timezone.utc).isoformat()

        cursor = await self._conn.execute("""
            INSERT INTO ingestion_logs (time, item_url, action, result, message)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
        """, (when_iso, item_url, action, result, message))

        row = await cursor.fetchone()
        await self._conn.commit()
        return str(row[0])

    # Query methods for future web UI

    async def get_recent_videos(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent videos ordered by published date.

        Args:
            limit: Maximum number of videos to return

        Returns:
            List of video dictionaries
        """
        async with self._conn.execute("""
            SELECT id, url, title, thumbnail_url, summary, source, published_at, updated_at
            FROM videos
            ORDER BY published_at DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "url": row[1],
                    "title": row[2],
                    "thumbnail_url": row[3],
                    "summary": row[4],
                    "source": row[5],
                    "published_at": row[6],
                    "updated_at": row[7],
                }
                for row in rows
            ]

    async def get_recent_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent articles ordered by published date.

        Args:
            limit: Maximum number of articles to return

        Returns:
            List of article dictionaries
        """
        async with self._conn.execute("""
            SELECT id, url, title, summary, body, source, published_at, updated_at
            FROM articles
            ORDER BY published_at DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "url": row[1],
                    "title": row[2],
                    "summary": row[3],
                    "body": row[4],
                    "source": row[5],
                    "published_at": row[6],
                    "updated_at": row[7],
                }
                for row in rows
            ]

    async def search_videos(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search videos using full-text search.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching video dictionaries
        """
        async with self._conn.execute("""
            SELECT v.id, v.url, v.title, v.thumbnail_url, v.summary, v.source, v.published_at, v.updated_at
            FROM videos v
            JOIN videos_fts fts ON v.id = fts.rowid
            WHERE videos_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "url": row[1],
                    "title": row[2],
                    "thumbnail_url": row[3],
                    "summary": row[4],
                    "source": row[5],
                    "published_at": row[6],
                    "updated_at": row[7],
                }
                for row in rows
            ]

    async def search_articles(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search articles using full-text search.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching article dictionaries
        """
        async with self._conn.execute("""
            SELECT a.id, a.url, a.title, a.summary, a.body, a.source, a.published_at, a.updated_at
            FROM articles a
            JOIN articles_fts fts ON a.id = fts.rowid
            WHERE articles_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "url": row[1],
                    "title": row[2],
                    "summary": row[3],
                    "body": row[4],
                    "source": row[5],
                    "published_at": row[6],
                    "updated_at": row[7],
                }
                for row in rows
            ]


async def init_database(db_path: Optional[Path] = None) -> DatabaseWriter:
    """Initialize database and return writer instance.

    Args:
        db_path: Optional custom database path

    Returns:
        Connected DatabaseWriter instance
    """
    writer = DatabaseWriter(db_path)
    await writer.connect()
    return writer
