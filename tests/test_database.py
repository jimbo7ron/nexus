"""Comprehensive unit tests for database module and related components.

This test suite covers:
- DatabaseWriter connection and lifecycle management
- Video and article CRUD operations
- Log event recording
- Query methods (get_recent, search with FTS5)
- Writer configuration (tools/config.py)
- Writer factory pattern (tools/writer_factory.py)
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from tools.database import DatabaseWriter, init_database
from tools.config import WriterConfig, load_writer_config, save_writer_config
from tools.writer_factory import create_writer


# =============================================================================
# DatabaseWriter Connection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_database_connect_disconnect(tmp_path):
    """Test database connection and disconnection lifecycle."""
    db_path = tmp_path / "test.db"
    writer = DatabaseWriter(db_path)

    # Initially not connected
    assert writer._conn is None

    # Connect
    await writer.connect()
    assert writer._conn is not None

    # Close
    await writer.close()
    assert writer._conn is None


@pytest.mark.asyncio
async def test_database_context_manager(tmp_path):
    """Test async context manager (async with) usage."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Should be connected inside context
        assert writer._conn is not None

        # Should be able to perform operations
        video_id = await writer.upsert_video(
            title="Test Video",
            url="https://example.com/video",
        )
        assert isinstance(video_id, str)

    # Connection should be closed after context
    assert writer._conn is None


@pytest.mark.asyncio
async def test_schema_creation(tmp_path):
    """Test that schema is created correctly with tables, indexes, and FTS."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Check that tables exist
        cursor = await writer._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

        assert "videos" in tables
        assert "articles" in tables
        assert "ingestion_logs" in tables
        assert "videos_fts" in tables
        assert "articles_fts" in tables

        # Check that indexes exist
        cursor = await writer._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indexes = [row[0] for row in await cursor.fetchall()]

        assert "idx_videos_url" in indexes
        assert "idx_videos_published" in indexes
        assert "idx_videos_updated" in indexes
        assert "idx_videos_source" in indexes
        assert "idx_articles_url" in indexes
        assert "idx_articles_published" in indexes
        assert "idx_articles_updated" in indexes
        assert "idx_articles_source" in indexes
        assert "idx_logs_time" in indexes
        assert "idx_logs_url" in indexes
        assert "idx_logs_action_result" in indexes


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path):
    """Test that WAL mode is enabled for better concurrency."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        cursor = await writer._conn.execute("PRAGMA journal_mode")
        mode = (await cursor.fetchone())[0]
        assert mode.upper() == "WAL"


@pytest.mark.asyncio
async def test_foreign_keys_enabled(tmp_path):
    """Test that foreign keys constraint enforcement is enabled."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        cursor = await writer._conn.execute("PRAGMA foreign_keys")
        enabled = (await cursor.fetchone())[0]
        assert enabled == 1


# =============================================================================
# Video Operations Tests
# =============================================================================


@pytest.mark.asyncio
async def test_upsert_video_insert_new(tmp_path):
    """Test inserting a new video."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        video_id = await writer.upsert_video(
            title="Introduction to Python",
            url="https://youtube.com/watch?v=abc123",
            summary="A beginner's guide to Python programming",
            thumbnail="https://img.youtube.com/vi/abc123/default.jpg",
            source="Tech Channel",
            published_iso="2024-01-15T10:00:00Z",
            last_updated_iso="2024-01-15T10:00:00Z",
        )

        # Should return string ID
        assert isinstance(video_id, str)
        assert int(video_id) > 0

        # Verify data was inserted
        cursor = await writer._conn.execute(
            "SELECT title, url, summary, source FROM videos WHERE id = ?",
            (video_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "Introduction to Python"
        assert row[1] == "https://youtube.com/watch?v=abc123"
        assert row[2] == "A beginner's guide to Python programming"
        assert row[3] == "Tech Channel"


@pytest.mark.asyncio
async def test_upsert_video_update_existing(tmp_path):
    """Test updating an existing video by URL."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        url = "https://youtube.com/watch?v=xyz789"

        # Insert initial video
        id1 = await writer.upsert_video(
            title="Original Title",
            url=url,
            summary="Original summary",
        )

        # Update with same URL
        id2 = await writer.upsert_video(
            title="Updated Title",
            url=url,
            summary="Updated summary with more details",
        )

        # Should return same ID (update, not insert)
        assert id1 == id2

        # Verify data was updated
        cursor = await writer._conn.execute(
            "SELECT title, summary FROM videos WHERE id = ?",
            (id1,)
        )
        row = await cursor.fetchone()
        assert row[0] == "Updated Title"
        assert row[1] == "Updated summary with more details"

        # Should only be one row with this URL
        cursor = await writer._conn.execute(
            "SELECT COUNT(*) FROM videos WHERE url = ?",
            (url,)
        )
        count = (await cursor.fetchone())[0]
        assert count == 1


@pytest.mark.asyncio
async def test_upsert_video_returns_string_id(tmp_path):
    """Test that upsert_video returns ID as string (NotionWriter compatibility)."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        video_id = await writer.upsert_video(
            title="Test Video",
            url="https://example.com/test",
        )

        assert isinstance(video_id, str)
        # Should be convertible to int
        assert int(video_id) > 0


@pytest.mark.asyncio
async def test_upsert_video_minimal_fields(tmp_path):
    """Test upsert_video with only required fields (title + url)."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        video_id = await writer.upsert_video(
            title="Minimal Video",
            url="https://example.com/minimal",
        )

        # Should succeed
        assert isinstance(video_id, str)

        # Optional fields should be empty/null
        cursor = await writer._conn.execute(
            "SELECT summary, thumbnail_url, source, published_at FROM videos WHERE id = ?",
            (video_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == ""  # summary
        assert row[1] == ""  # thumbnail_url
        assert row[2] == ""  # source
        assert row[3] is None  # published_at


@pytest.mark.asyncio
async def test_upsert_video_all_fields_populated(tmp_path):
    """Test upsert_video with all fields populated."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        video_id = await writer.upsert_video(
            title="Complete Video",
            url="https://example.com/complete",
            summary="This is a complete video with all fields",
            thumbnail="https://example.com/thumb.jpg",
            source="Example Channel",
            published_iso="2024-01-01T12:00:00Z",
            last_updated_iso="2024-01-02T12:00:00Z",
        )

        # Verify all fields were saved
        cursor = await writer._conn.execute(
            """SELECT title, url, summary, thumbnail_url, source,
                      published_at, last_updated_at
               FROM videos WHERE id = ?""",
            (video_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "Complete Video"
        assert row[1] == "https://example.com/complete"
        assert row[2] == "This is a complete video with all fields"
        assert row[3] == "https://example.com/thumb.jpg"
        assert row[4] == "Example Channel"
        assert row[5] == "2024-01-01T12:00:00Z"
        assert row[6] == "2024-01-02T12:00:00Z"


@pytest.mark.asyncio
async def test_video_url_uniqueness_constraint(tmp_path):
    """Test that URL uniqueness is enforced for videos."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        url = "https://example.com/unique"

        # Insert first video
        id1 = await writer.upsert_video(
            title="First Video",
            url=url,
        )

        # Insert with same URL should update, not create duplicate
        id2 = await writer.upsert_video(
            title="Second Video",
            url=url,
        )

        # Should be same ID (updated, not inserted)
        assert id1 == id2

        # Should only have one row
        cursor = await writer._conn.execute(
            "SELECT COUNT(*) FROM videos WHERE url = ?",
            (url,)
        )
        count = (await cursor.fetchone())[0]
        assert count == 1


# =============================================================================
# Article Operations Tests
# =============================================================================


@pytest.mark.asyncio
async def test_upsert_article_insert_new(tmp_path):
    """Test inserting a new article."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        article_id = await writer.upsert_article(
            title="How to Build a Database",
            url="https://blog.example.com/database-guide",
            summary="A comprehensive guide to building databases",
            body="Full article text here...",
            source="Hacker News (250 points)",
            published_iso="2024-02-01T14:30:00Z",
            last_updated_iso="2024-02-01T14:30:00Z",
        )

        # Should return string ID
        assert isinstance(article_id, str)
        assert int(article_id) > 0

        # Verify data was inserted
        cursor = await writer._conn.execute(
            "SELECT title, url, summary, source FROM articles WHERE id = ?",
            (article_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "How to Build a Database"
        assert row[1] == "https://blog.example.com/database-guide"
        assert row[2] == "A comprehensive guide to building databases"
        assert row[3] == "Hacker News (250 points)"


@pytest.mark.asyncio
async def test_upsert_article_update_existing(tmp_path):
    """Test updating an existing article by URL."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        url = "https://blog.example.com/article"

        # Insert initial article
        id1 = await writer.upsert_article(
            title="Original Article",
            url=url,
            summary="Original summary",
        )

        # Update with same URL
        id2 = await writer.upsert_article(
            title="Updated Article",
            url=url,
            summary="Updated summary",
            body="Now with body text",
        )

        # Should return same ID (update, not insert)
        assert id1 == id2

        # Verify data was updated
        cursor = await writer._conn.execute(
            "SELECT title, summary, body FROM articles WHERE id = ?",
            (id1,)
        )
        row = await cursor.fetchone()
        assert row[0] == "Updated Article"
        assert row[1] == "Updated summary"
        assert row[2] == "Now with body text"

        # Should only be one row with this URL
        cursor = await writer._conn.execute(
            "SELECT COUNT(*) FROM articles WHERE url = ?",
            (url,)
        )
        count = (await cursor.fetchone())[0]
        assert count == 1


@pytest.mark.asyncio
async def test_upsert_article_returns_string_id(tmp_path):
    """Test that upsert_article returns ID as string (NotionWriter compatibility)."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        article_id = await writer.upsert_article(
            title="Test Article",
            url="https://example.com/test",
        )

        assert isinstance(article_id, str)
        # Should be convertible to int
        assert int(article_id) > 0


@pytest.mark.asyncio
async def test_upsert_article_minimal_fields(tmp_path):
    """Test upsert_article with only required fields (title + url)."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        article_id = await writer.upsert_article(
            title="Minimal Article",
            url="https://example.com/minimal-article",
        )

        # Should succeed
        assert isinstance(article_id, str)

        # Optional fields should be empty/null
        cursor = await writer._conn.execute(
            "SELECT summary, body, source, published_at FROM articles WHERE id = ?",
            (article_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == ""  # summary
        assert row[1] == ""  # body
        assert row[2] == ""  # source
        assert row[3] is None  # published_at


@pytest.mark.asyncio
async def test_upsert_article_all_fields_populated(tmp_path):
    """Test upsert_article with all fields populated."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        article_id = await writer.upsert_article(
            title="Complete Article",
            url="https://example.com/complete-article",
            summary="A complete article summary",
            body="This is the full body text of the article with lots of content.",
            source="Tech Blog (HN 500 points)",
            published_iso="2024-03-01T09:00:00Z",
            last_updated_iso="2024-03-02T09:00:00Z",
        )

        # Verify all fields were saved
        cursor = await writer._conn.execute(
            """SELECT title, url, summary, body, source,
                      published_at, last_updated_at
               FROM articles WHERE id = ?""",
            (article_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == "Complete Article"
        assert row[1] == "https://example.com/complete-article"
        assert row[2] == "A complete article summary"
        assert row[3] == "This is the full body text of the article with lots of content."
        assert row[4] == "Tech Blog (HN 500 points)"
        assert row[5] == "2024-03-01T09:00:00Z"
        assert row[6] == "2024-03-02T09:00:00Z"


# =============================================================================
# Log Event Tests
# =============================================================================


@pytest.mark.asyncio
async def test_log_event_auto_timestamp(tmp_path):
    """Test log_event with auto-generated timestamp."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        before = datetime.now(timezone.utc)

        log_id = await writer.log_event(
            item_url="https://example.com/item",
            action="fetch",
            result="ok",
            message="Successfully fetched content",
        )

        after = datetime.now(timezone.utc)

        # Should return string ID
        assert isinstance(log_id, str)

        # Verify log was created with auto timestamp
        cursor = await writer._conn.execute(
            "SELECT time, item_url, action, result, message FROM ingestion_logs WHERE id = ?",
            (log_id,)
        )
        row = await cursor.fetchone()

        # Parse timestamp
        log_time = datetime.fromisoformat(row[0].replace('Z', '+00:00'))

        # Should be between before and after
        assert before <= log_time <= after
        assert row[1] == "https://example.com/item"
        assert row[2] == "fetch"
        assert row[3] == "ok"
        assert row[4] == "Successfully fetched content"


@pytest.mark.asyncio
async def test_log_event_explicit_timestamp(tmp_path):
    """Test log_event with explicit when_iso parameter."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        explicit_time = "2024-01-15T10:30:00Z"

        log_id = await writer.log_event(
            item_url="https://example.com/item2",
            action="summarize",
            result="ok",
            message="Generated summary",
            when_iso=explicit_time,
        )

        # Verify explicit timestamp was used
        cursor = await writer._conn.execute(
            "SELECT time FROM ingestion_logs WHERE id = ?",
            (log_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == explicit_time


@pytest.mark.asyncio
async def test_log_event_returns_string_id(tmp_path):
    """Test that log_event returns ID as string (NotionWriter compatibility)."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        log_id = await writer.log_event(
            item_url="https://example.com/item3",
            action="write",
            result="ok",
        )

        assert isinstance(log_id, str)
        # Should be convertible to int
        assert int(log_id) > 0


@pytest.mark.asyncio
async def test_log_event_action_constraint(tmp_path):
    """Test that invalid action values are rejected by constraint."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Valid actions: discover, fetch, summarize, write
        with pytest.raises(Exception):  # aiosqlite.IntegrityError
            await writer.log_event(
                item_url="https://example.com/item",
                action="invalid_action",
                result="ok",
            )


@pytest.mark.asyncio
async def test_log_event_result_constraint(tmp_path):
    """Test that invalid result values are rejected by constraint."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Valid results: ok, skip, error
        with pytest.raises(Exception):  # aiosqlite.IntegrityError
            await writer.log_event(
                item_url="https://example.com/item",
                action="fetch",
                result="invalid_result",
            )


# =============================================================================
# Query Methods Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_recent_videos_ordering_and_limit(tmp_path):
    """Test get_recent_videos returns videos in correct order with limit."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Insert videos with different publish dates
        await writer.upsert_video(
            title="Old Video",
            url="https://example.com/old",
            published_iso="2024-01-01T10:00:00Z",
        )
        await writer.upsert_video(
            title="Recent Video",
            url="https://example.com/recent",
            published_iso="2024-03-01T10:00:00Z",
        )
        await writer.upsert_video(
            title="Newest Video",
            url="https://example.com/newest",
            published_iso="2024-04-01T10:00:00Z",
        )

        # Get recent videos (default limit)
        videos = await writer.get_recent_videos(limit=2)

        # Should return 2 videos
        assert len(videos) == 2

        # Should be ordered by published_at DESC (newest first)
        assert videos[0]["title"] == "Newest Video"
        assert videos[1]["title"] == "Recent Video"

        # Check structure
        assert "id" in videos[0]
        assert "url" in videos[0]
        assert "title" in videos[0]
        assert "summary" in videos[0]
        assert "published_at" in videos[0]


@pytest.mark.asyncio
async def test_get_recent_articles_ordering_and_limit(tmp_path):
    """Test get_recent_articles returns articles in correct order with limit."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Insert articles with different publish dates
        await writer.upsert_article(
            title="Old Article",
            url="https://example.com/old-article",
            published_iso="2024-01-01T10:00:00Z",
        )
        await writer.upsert_article(
            title="Recent Article",
            url="https://example.com/recent-article",
            published_iso="2024-03-01T10:00:00Z",
        )
        await writer.upsert_article(
            title="Newest Article",
            url="https://example.com/newest-article",
            published_iso="2024-04-01T10:00:00Z",
        )

        # Get recent articles (limit=2)
        articles = await writer.get_recent_articles(limit=2)

        # Should return 2 articles
        assert len(articles) == 2

        # Should be ordered by published_at DESC (newest first)
        assert articles[0]["title"] == "Newest Article"
        assert articles[1]["title"] == "Recent Article"

        # Check structure
        assert "id" in articles[0]
        assert "url" in articles[0]
        assert "title" in articles[0]
        assert "summary" in articles[0]
        assert "body" in articles[0]
        assert "published_at" in articles[0]


@pytest.mark.asyncio
async def test_search_videos_fts5(tmp_path):
    """Test search_videos uses FTS5 full-text search correctly."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Insert videos with searchable content
        await writer.upsert_video(
            title="Python Programming Tutorial",
            url="https://example.com/python",
            summary="Learn Python from scratch with this comprehensive tutorial",
        )
        await writer.upsert_video(
            title="JavaScript Basics",
            url="https://example.com/javascript",
            summary="Introduction to JavaScript programming",
        )
        await writer.upsert_video(
            title="Advanced Python Techniques",
            url="https://example.com/python-advanced",
            summary="Master advanced Python patterns and best practices",
        )

        # Update FTS index
        await writer._conn.execute(
            "INSERT INTO videos_fts(videos_fts) VALUES('rebuild')"
        )
        await writer._conn.commit()

        # Search for Python videos
        results = await writer.search_videos("Python")

        # Should find both Python videos
        assert len(results) == 2
        titles = [r["title"] for r in results]
        assert "Python Programming Tutorial" in titles
        assert "Advanced Python Techniques" in titles

        # Search for JavaScript
        results = await writer.search_videos("JavaScript")
        assert len(results) == 1
        assert results[0]["title"] == "JavaScript Basics"


@pytest.mark.asyncio
async def test_search_articles_fts5(tmp_path):
    """Test search_articles uses FTS5 full-text search correctly."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Insert articles with searchable content
        await writer.upsert_article(
            title="Building Scalable Databases",
            url="https://example.com/db1",
            summary="How to design databases that scale",
            body="This article covers sharding, replication, and partitioning...",
        )
        await writer.upsert_article(
            title="Introduction to NoSQL",
            url="https://example.com/nosql",
            summary="Understanding NoSQL databases",
            body="NoSQL databases provide flexible schemas and horizontal scaling...",
        )
        await writer.upsert_article(
            title="Database Performance Tuning",
            url="https://example.com/db-perf",
            summary="Optimize your database queries",
            body="Learn indexing strategies and query optimization techniques...",
        )

        # Update FTS index
        await writer._conn.execute(
            "INSERT INTO articles_fts(articles_fts) VALUES('rebuild')"
        )
        await writer._conn.commit()

        # Search for database articles (case-insensitive search)
        results = await writer.search_articles("databases")

        # Should find articles mentioning databases
        assert len(results) >= 2

        # Search for scaling
        results = await writer.search_articles("horizontal")
        assert len(results) >= 1

        # Check result structure
        if results:
            assert "id" in results[0]
            assert "title" in results[0]
            assert "summary" in results[0]
            assert "body" in results[0]


# =============================================================================
# Configuration Tests (tools/config.py)
# =============================================================================


def test_writer_config_defaults():
    """Test WriterConfig uses correct defaults."""
    config = WriterConfig()

    assert config.backend == "sqlite"
    assert config.db_path is None


def test_load_writer_config_creates_default_if_missing(tmp_path, monkeypatch):
    """Test load_writer_config creates default config if file doesn't exist."""
    # Mock the config directory
    config_dir = tmp_path / "config"
    config_path = config_dir / "writer.json"

    from tools import config as cfg_module
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_module, "WRITER_CONFIG_PATH", config_path)

    # File shouldn't exist yet
    assert not config_path.exists()

    # Load should create default
    config = load_writer_config()

    # Should have defaults
    assert config.backend == "sqlite"
    assert config.db_path is None

    # File should now exist
    assert config_path.exists()

    # Should be valid JSON
    data = json.loads(config_path.read_text())
    assert data["backend"] == "sqlite"


def test_save_writer_config_persists_to_json(tmp_path, monkeypatch):
    """Test save_writer_config writes config to JSON file."""
    # Mock the config directory
    config_dir = tmp_path / "config"
    config_path = config_dir / "writer.json"

    from tools import config as cfg_module
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_module, "WRITER_CONFIG_PATH", config_path)

    # Create custom config
    config = WriterConfig(
        backend="notion",
        db_path=Path("/custom/path/db.sqlite"),
    )

    # Save it
    save_writer_config(config)

    # File should exist
    assert config_path.exists()

    # Load and verify
    data = json.loads(config_path.read_text())
    assert data["backend"] == "notion"
    assert data["db_path"] == "/custom/path/db.sqlite"


def test_writer_config_path_serialization(tmp_path, monkeypatch):
    """Test that Path objects are correctly serialized/deserialized."""
    # Mock the config directory
    config_dir = tmp_path / "config"
    config_path = config_dir / "writer.json"

    from tools import config as cfg_module
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_module, "WRITER_CONFIG_PATH", config_path)

    # Create config with Path
    original_path = Path("/test/database.sqlite")
    config = WriterConfig(backend="sqlite", db_path=original_path)

    # Save
    save_writer_config(config)

    # Load back
    loaded_config = load_writer_config()

    # Should deserialize back to Path
    assert isinstance(loaded_config.db_path, Path)
    assert loaded_config.db_path == original_path


# =============================================================================
# Factory Pattern Tests (tools/writer_factory.py)
# =============================================================================


def test_create_writer_sqlite_backend(tmp_path):
    """Test create_writer returns DatabaseWriter for sqlite backend."""
    config = WriterConfig(
        backend="sqlite",
        db_path=tmp_path / "test.db",
    )

    writer = create_writer(config)

    # Should return DatabaseWriter instance
    assert isinstance(writer, DatabaseWriter)
    assert writer.db_path == tmp_path / "test.db"


@patch("tools.writer_factory.Client")
@patch("tools.writer_factory.load_notion_config")
def test_create_writer_notion_backend(mock_load_config, mock_client, tmp_path):
    """Test create_writer returns NotionWriter for notion backend (with mocked API)."""
    # Mock Notion config
    mock_notion_config = Mock()
    mock_notion_config.youtube_db_id = "youtube_123"
    mock_notion_config.articles_db_id = "articles_456"
    mock_notion_config.log_db_id = "log_789"
    mock_load_config.return_value = mock_notion_config

    # Mock Notion client
    mock_client_instance = Mock()
    mock_client.return_value = mock_client_instance

    config = WriterConfig(backend="notion")

    # Should create NotionWriter
    writer = create_writer(config, notion_token="test_token_123")

    # Verify Client was created with token
    mock_client.assert_called_once_with(auth="test_token_123")

    # Should be NotionWriter instance (check type name since we're mocking)
    from tools.notion import NotionWriter
    assert isinstance(writer, NotionWriter)


def test_create_writer_unknown_backend():
    """Test create_writer raises ValueError for unknown backend."""
    config = WriterConfig(backend="unknown_backend")

    with pytest.raises(ValueError) as exc_info:
        create_writer(config)

    assert "Unknown backend" in str(exc_info.value)
    assert "unknown_backend" in str(exc_info.value)


def test_create_writer_notion_without_token():
    """Test create_writer raises ValueError for notion backend without token."""
    config = WriterConfig(backend="notion")

    with pytest.raises(ValueError) as exc_info:
        create_writer(config, notion_token=None)

    assert "NOTION_TOKEN is required" in str(exc_info.value)


@patch("tools.writer_factory.load_notion_config")
def test_create_writer_notion_missing_database_ids(mock_load_config):
    """Test create_writer raises ValueError when Notion database IDs are missing."""
    # Mock incomplete Notion config
    mock_notion_config = Mock()
    mock_notion_config.youtube_db_id = ""
    mock_notion_config.articles_db_id = ""
    mock_notion_config.log_db_id = ""
    mock_load_config.return_value = mock_notion_config

    config = WriterConfig(backend="notion")

    with pytest.raises(ValueError) as exc_info:
        create_writer(config, notion_token="test_token")

    assert "database IDs are not configured" in str(exc_info.value)


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_init_database_helper(tmp_path):
    """Test init_database helper function."""
    db_path = tmp_path / "test.db"

    writer = await init_database(db_path)

    # Should be connected and ready
    assert writer._conn is not None
    assert isinstance(writer, DatabaseWriter)

    # Should be able to use immediately
    video_id = await writer.upsert_video(
        title="Test",
        url="https://example.com/test",
    )
    assert isinstance(video_id, str)

    # Clean up
    await writer.close()


@pytest.mark.asyncio
async def test_concurrent_operations(tmp_path):
    """Test that multiple operations can be performed in sequence."""
    db_path = tmp_path / "test.db"

    async with DatabaseWriter(db_path) as writer:
        # Insert video
        video_id = await writer.upsert_video(
            title="Test Video",
            url="https://example.com/video",
        )

        # Insert article
        article_id = await writer.upsert_article(
            title="Test Article",
            url="https://example.com/article",
        )

        # Log event
        log_id = await writer.log_event(
            item_url="https://example.com/video",
            action="write",
            result="ok",
        )

        # All should succeed
        assert isinstance(video_id, str)
        assert isinstance(article_id, str)
        assert isinstance(log_id, str)

        # Query back
        videos = await writer.get_recent_videos()
        articles = await writer.get_recent_articles()

        assert len(videos) == 1
        assert len(articles) == 1
