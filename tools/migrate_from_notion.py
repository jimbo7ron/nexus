"""Migrate data from Notion to SQLite database.

This script exports all content from Notion databases and imports it into
the local SQLite database. It can be run multiple times safely (idempotent).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

from notion_client import Client
from rich import print
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import load_notion_config, get_notion_token
from .database import DatabaseWriter


# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds


async def retry_on_database_locked(func, *args, **kwargs):
    """Retry a database operation if it fails due to database lock.

    Args:
        func: Async function to call
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        Exception: If all retries fail
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "sqlite" in error_msg:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    print(f"[yellow]Database locked, retrying in {wait_time}s...[/yellow]")
                    await asyncio.sleep(wait_time)
                    continue
            # Not a database lock error, or final retry failed
            raise
    # All retries exhausted
    raise last_error


async def export_notion_videos(client: Client, database_id: str) -> List[Dict[str, Any]]:
    """Export all videos from Notion YouTube database.

    Args:
        client: Notion client
        database_id: YouTube database ID

    Returns:
        List of video dictionaries
    """
    videos = []
    has_more = True
    start_cursor = None

    while has_more:
        # Query Notion database with pagination
        response = client.databases.query(
            database_id=database_id,
            start_cursor=start_cursor,
        )

        for page in response["results"]:
            props = page["properties"]

            # Extract properties (handle Notion's nested structure)
            # Note: Notion uses "Name" as the default title property
            url = _get_url_property(props.get("Link", {}))
            title = _get_title_property(props.get("Name", {}))
            summary = _get_text_property(props.get("Summary", {}))
            thumbnail = _get_url_property(props.get("Thumbnail", {}))
            source = _get_text_property(props.get("Source", {}))
            published = _get_date_property(props.get("Published", {}))
            updated = _get_date_property(props.get("Last Updated", {}))

            if url and title:  # Only include if we have required fields
                videos.append({
                    "url": url,
                    "title": title,
                    "summary": summary or "",
                    "thumbnail": thumbnail or "",
                    "source": source or "",
                    "published_iso": published,
                    "last_updated_iso": updated,
                })

        has_more = response["has_more"]
        start_cursor = response.get("next_cursor")

    return videos


async def export_notion_articles(client: Client, database_id: str) -> List[Dict[str, Any]]:
    """Export all articles from Notion Articles database.

    Args:
        client: Notion client
        database_id: Articles database ID

    Returns:
        List of article dictionaries
    """
    articles = []
    has_more = True
    start_cursor = None

    while has_more:
        response = client.databases.query(
            database_id=database_id,
            start_cursor=start_cursor,
        )

        for page in response["results"]:
            props = page["properties"]

            # Note: Notion uses "Name" as the default title property
            url = _get_url_property(props.get("Link", {}))
            title = _get_title_property(props.get("Name", {}))
            summary = _get_text_property(props.get("Summary", {}))
            body = _get_text_property(props.get("Body", {}))
            source = _get_text_property(props.get("Source", {}))
            published = _get_date_property(props.get("Published", {}))
            updated = _get_date_property(props.get("Last Updated", {}))

            if url and title:
                articles.append({
                    "url": url,
                    "title": title,
                    "summary": summary or "",
                    "body": body or "",
                    "source": source or "",
                    "published_iso": published,
                    "last_updated_iso": updated,
                })

        has_more = response["has_more"]
        start_cursor = response.get("next_cursor")

    return articles


async def export_notion_logs(client: Client, database_id: str) -> List[Dict[str, Any]]:
    """Export ingestion logs from Notion.

    Args:
        client: Notion client
        database_id: Ingestion Log database ID

    Returns:
        List of log dictionaries
    """
    logs = []
    has_more = True
    start_cursor = None

    while has_more:
        response = client.databases.query(
            database_id=database_id,
            start_cursor=start_cursor,
        )

        for page in response["results"]:
            props = page["properties"]

            time = _get_date_property(props.get("Time", {}))
            url = _get_url_property(props.get("Item URL", {}))
            action = _get_select_property(props.get("Action", {}))
            result = _get_select_property(props.get("Result", {}))
            message = _get_text_property(props.get("Message", {}))

            if time and url and action and result:
                logs.append({
                    "time": time,
                    "item_url": url,
                    "action": action.lower(),
                    "result": result.lower(),
                    "message": message or "",
                })

        has_more = response["has_more"]
        start_cursor = response.get("next_cursor")

    return logs


# Helper functions to extract Notion property values

def _get_title_property(prop: Dict) -> str:
    """Extract title from Notion title property."""
    if prop.get("type") == "title" and prop.get("title"):
        parts = [t["plain_text"] for t in prop["title"]]
        return "".join(parts)
    return ""


def _get_text_property(prop: Dict) -> str:
    """Extract text from Notion rich_text property."""
    if prop.get("type") == "rich_text" and prop.get("rich_text"):
        parts = [t["plain_text"] for t in prop["rich_text"]]
        return "".join(parts)
    return ""


def _get_url_property(prop: Dict) -> str:
    """Extract URL from Notion url property."""
    if prop.get("type") == "url":
        return prop.get("url") or ""
    return ""


def _get_date_property(prop: Dict) -> str:
    """Extract ISO date from Notion date property."""
    if prop.get("type") == "date" and prop.get("date"):
        start = prop["date"].get("start")
        if start:
            return start
    return ""


def _get_select_property(prop: Dict) -> str:
    """Extract value from Notion select property."""
    if prop.get("type") == "select" and prop.get("select"):
        return prop["select"].get("name", "")
    return ""


async def main():
    """Main migration function."""
    print("[bold cyan]Nexus Migration: Notion → SQLite[/bold cyan]\n")

    # Get Notion credentials
    token = get_notion_token()
    if not token:
        print("[red]ERROR:[/red] NOTION_TOKEN environment variable not set")
        sys.exit(1)

    # Load Notion config
    config = load_notion_config()
    if not config.youtube_db_id or not config.articles_db_id or not config.log_db_id:
        print("[red]ERROR:[/red] Notion database IDs not found in config/notion.json")
        print("Run 'nexus notion --parent-page-id <id>' first to bootstrap databases")
        sys.exit(1)

    # Initialize Notion client with error handling
    try:
        client = Client(auth=token)
    except Exception as e:
        print(f"[red]ERROR:[/red] Failed to initialize Notion client: {str(e)}")
        sys.exit(1)

    # Initialize database
    print("[cyan]Initializing SQLite database...[/cyan]")
    db_writer = DatabaseWriter()
    try:
        await db_writer.connect()
    except Exception as e:
        print(f"[red]ERROR:[/red] Failed to connect to SQLite database: {str(e)}")
        sys.exit(1)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:

            # Export videos
            task = progress.add_task("Exporting videos from Notion...", total=None)
            try:
                videos = await export_notion_videos(client, config.youtube_db_id)
                progress.update(task, completed=True)
                print(f"  ✓ Exported {len(videos)} videos")
            except Exception as e:
                print(f"[red]ERROR:[/red] Failed to export videos: {str(e)}")
                raise

            # Export articles
            task = progress.add_task("Exporting articles from Notion...", total=None)
            try:
                articles = await export_notion_articles(client, config.articles_db_id)
                progress.update(task, completed=True)
                print(f"  ✓ Exported {len(articles)} articles")
            except Exception as e:
                print(f"[red]ERROR:[/red] Failed to export articles: {str(e)}")
                raise

            # Export logs
            task = progress.add_task("Exporting ingestion logs from Notion...", total=None)
            try:
                logs = await export_notion_logs(client, config.log_db_id)
                progress.update(task, completed=True)
                print(f"  ✓ Exported {len(logs)} log entries")
            except Exception as e:
                print(f"[red]ERROR:[/red] Failed to export logs: {str(e)}")
                raise

        # Import into SQLite
        print("\n[cyan]Importing into SQLite...[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:

            # Import videos (with transaction support and retry logic)
            task = progress.add_task(f"Importing {len(videos)} videos...", total=len(videos))
            batch_size = 100  # Process in batches for better transaction management

            for i in range(0, len(videos), batch_size):
                batch = videos[i:i + batch_size]
                # Wrap batch in transaction for atomicity
                async def import_video_batch():
                    for video in batch:
                        await db_writer.upsert_video(**video)
                        progress.advance(task)

                await retry_on_database_locked(import_video_batch)

            print(f"  ✓ Imported {len(videos)} videos")

            # Import articles (with transaction support and retry logic)
            task = progress.add_task(f"Importing {len(articles)} articles...", total=len(articles))

            for i in range(0, len(articles), batch_size):
                batch = articles[i:i + batch_size]
                async def import_article_batch():
                    for article in batch:
                        await db_writer.upsert_article(**article)
                        progress.advance(task)

                await retry_on_database_locked(import_article_batch)

            print(f"  ✓ Imported {len(articles)} articles")

            # Import logs (with transaction support and retry logic)
            task = progress.add_task(f"Importing {len(logs)} logs...", total=len(logs))

            for i in range(0, len(logs), batch_size):
                batch = logs[i:i + batch_size]
                async def import_log_batch():
                    for log in batch:
                        # Insert logs directly (no upsert needed)
                        await db_writer._conn.execute("""
                            INSERT OR IGNORE INTO ingestion_logs (time, item_url, action, result, message)
                            VALUES (?, ?, ?, ?, ?)
                        """, (log["time"], log["item_url"], log["action"], log["result"], log["message"]))
                        progress.advance(task)
                    await db_writer._conn.commit()

                await retry_on_database_locked(import_log_batch)

            print(f"  ✓ Imported {len(logs)} log entries")

    except Exception as e:
        print(f"\n[red]MIGRATION FAILED:[/red] {str(e)}")
        await db_writer.close()
        sys.exit(1)

    await db_writer.close()

    # Verification
    print("\n[cyan]Verifying migration...[/cyan]")
    db_writer = DatabaseWriter()
    await db_writer.connect()

    db_videos = await db_writer.get_recent_videos(limit=10000)
    db_articles = await db_writer.get_recent_articles(limit=10000)

    print(f"  ✓ Database contains {len(db_videos)} videos")
    print(f"  ✓ Database contains {len(db_articles)} articles")

    await db_writer.close()

    # Summary
    print("\n[bold green]Migration Complete![/bold green]")
    print(f"Database location: [cyan]{db_writer.db_path}[/cyan]")
    print("\nNext steps:")
    print("  1. Update CLI tools to use DatabaseWriter instead of NotionWriter")
    print("  2. Test ingestion with: ./nexus ingest-youtube --since 1 --console")
    print("  3. Verify data in web UI (once built)")


if __name__ == "__main__":
    asyncio.run(main())
