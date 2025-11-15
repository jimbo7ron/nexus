from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path

# Suppress known warnings for Python 3.9 and LibreSSL
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core._python_version_support")
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import typer
from notion_client import Client
from rich import print

from .config import (
    load_notion_config,
    save_notion_config,
    get_notion_token,
    load_writer_config,
    WriterConfig,
)
from .notion import (
    build_youtube_properties,
    build_articles_properties,
    build_log_properties,
    ensure_database,
    NotionWriter,
)
from .writer_factory import create_writer
from .database import DatabaseWriter
from .ingest_youtube import ingest_youtube, ingest_youtube_url, FatalIngestionError
from .ingest_news import ingest_news_since
from .ingest_hackernews import ingest_hackernews


app = typer.Typer(help="Nexus CLI")


@app.command("notion")
def notion_bootstrap(
    parent_page_id: str = typer.Option(
        "",
        help="Notion parent page ID. If omitted, uses config/notion.json parent_page_id",
    )
):
    """Ensure Content and Ingestion Log databases exist in Notion and save their IDs in config."""
    asyncio.run(_async_notion_bootstrap(parent_page_id))


async def _async_notion_bootstrap(parent_page_id: str):
    """Async implementation of notion bootstrap."""
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        raise typer.Exit(code=1)

    cfg = load_notion_config()
    if parent_page_id:
        cfg.parent_page_id = parent_page_id
        save_notion_config(cfg)

    if not cfg.parent_page_id:
        print(
            "[yellow]Missing parent_page_id[/yellow]: set it via `--parent-page-id` or in config/notion.json"
        )
        raise typer.Exit(code=2)

    client = Client(auth=token)

    # Ensure YouTube DB (video content)
    youtube_id = await ensure_database(
        client,
        cfg.parent_page_id,
        cfg.youtube_db_id,
        name="YouTube",
        properties=build_youtube_properties(),
    )
    # Ensure Articles DB (news articles and blog posts)
    articles_id = await ensure_database(
        client,
        cfg.parent_page_id,
        cfg.articles_db_id,
        name="Articles",
        properties=build_articles_properties(),
    )
    # Ensure Ingestion Log DB
    log_id = await ensure_database(
        client,
        cfg.parent_page_id,
        cfg.log_db_id,
        name="Ingestion Log",
        properties=build_log_properties(),
    )

    cfg.youtube_db_id = youtube_id
    cfg.articles_db_id = articles_id
    cfg.log_db_id = log_id
    save_notion_config(cfg)

    print("[green]OK[/green] Notion databases ensured.")
    print(f"YouTube DB ID: [bold]{youtube_id}[/bold]")
    print(f"Articles DB ID: [bold]{articles_id}[/bold]")
    print(f"Ingestion Log DB ID: [bold]{log_id}[/bold]")


async def _make_writer():
    """Create a writer instance based on config/writer.json backend setting.

    Returns:
        NotionWriter or DatabaseWriter instance

    Raises:
        typer.Exit: If configuration is invalid or connection fails
    """
    writer_config = load_writer_config()

    # Get token only if needed for Notion backend
    token = None
    if writer_config.backend == "notion":
        token = get_notion_token()
        if not token:
            print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
            print("Notion backend requires NOTION_TOKEN. Either:")
            print("  1. Set NOTION_TOKEN environment variable, or")
            print("  2. Switch to SQLite backend in config/writer.json")
            raise typer.Exit(code=1)

    # Create writer using factory
    try:
        writer = create_writer(writer_config, notion_token=token)
    except ValueError as e:
        print(f"[red]ERROR[/red]: {str(e)}")
        raise typer.Exit(code=3)

    # For Notion backend, validate databases exist
    if isinstance(writer, NotionWriter):
        try:
            writer.client.databases.retrieve(database_id=load_notion_config().youtube_db_id)
            writer.client.databases.retrieve(database_id=load_notion_config().articles_db_id)
            writer.client.databases.retrieve(database_id=load_notion_config().log_db_id)
        except Exception as e:
            print(f"[red]ERROR[/red]: Could not access Notion databases. Run `nexus notion` to recreate them.")
            print(f"Details: {str(e)}")
            raise typer.Exit(code=4)

    # For SQLite backend, ensure connection
    if isinstance(writer, DatabaseWriter):
        await writer.connect()

    return writer


@app.command("ingest-youtube")
def cmd_ingest_youtube(
    since: int = typer.Option(24, "--since", help="Hours to look back"),
    console: bool = typer.Option(False, "--console", help="Print one-line summary per video"),
    verbose: bool = typer.Option(False, "--verbose", help="Print detailed output"),
    workers: int = typer.Option(10, "--workers", help="Number of concurrent workers for parallel processing"),
):
    """Ingest YouTube videos from configured sources with parallel processing."""
    asyncio.run(_async_ingest_youtube(since, console, verbose, workers))


async def _async_ingest_youtube(since: int, console: bool, verbose: bool, workers: int):
    """Async implementation of YouTube ingestion."""
    writer = await _make_writer()
    try:
        count = await ingest_youtube(
            writer,
            since_hours=since,
            console=console,
            verbose=verbose,
            workers=workers,
        )
        print(f"[green]OK[/green] Ingested {count} YouTube videos")
    except FatalIngestionError as exc:
        print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=5)
    finally:
        if isinstance(writer, DatabaseWriter):
            await writer.close()


@app.command("ingest-news")
def cmd_ingest_news(
    since: int = typer.Option(24, help="Hours back to check"),
    console: bool = typer.Option(False, "--console", help="Print items to console as they are processed"),
):
    """Ingest news articles from RSS feeds configured in config/feeds.yaml."""
    asyncio.run(_async_ingest_news(since, console))


async def _async_ingest_news(since: int, console: bool):
    """Async implementation of news ingestion."""
    writer = await _make_writer()
    try:
        # News ingestion currently requires NotionWriter with client
        if not isinstance(writer, NotionWriter):
            print("[yellow]WARNING[/yellow]: News ingestion currently only works with Notion backend")
            print("Please set backend='notion' in config/writer.json or wait for SQLite support")
            raise typer.Exit(code=6)
        client = writer.client
        count = ingest_news_since(client, writer, since_hours=since, console=console)
        print(f"[green]OK[/green] Ingested {count} articles")
    finally:
        if isinstance(writer, DatabaseWriter):
            await writer.close()


@app.command("ingest-hackernews")
def cmd_ingest_hackernews(
    min_score: int = typer.Option(100, "--min-score", help="Minimum HN score threshold"),
    since: int = typer.Option(24, "--since", help="Hours to look back"),
    console: bool = typer.Option(False, "--console", help="Print one-line summary per story"),
    verbose: bool = typer.Option(False, "--verbose", help="Print detailed output (URLs, content preview, etc)"),
    workers: int = typer.Option(10, "--workers", help="Number of concurrent workers for parallel processing"),
):
    """Ingest high-scoring Hacker News stories (default: 100+ points, last 24h)."""
    asyncio.run(_async_ingest_hackernews(min_score, since, console, verbose, workers))


async def _async_ingest_hackernews(min_score: int, since: int, console: bool, verbose: bool, workers: int):
    """Async implementation of Hacker News ingestion."""
    writer = await _make_writer()
    try:
        count = await ingest_hackernews(
            writer,
            min_score=min_score,
            since_hours=since,
            console=console,
            verbose=verbose,
            workers=workers,
        )
        print(f"[green]OK[/green] Ingested {count} HN stories")
    finally:
        if isinstance(writer, DatabaseWriter):
            await writer.close()


@app.command("ingest-youtube-url")
def cmd_ingest_youtube_url(
    url: str = typer.Option(..., "--url", help="YouTube video URL"),
    console: bool = typer.Option(False, "--console", help="Print transcript preview to console"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write to database; console only"),
):
    """Ingest a single YouTube video by URL, with transcript and summary."""
    asyncio.run(_async_ingest_youtube_url(url, console, dry_run))


async def _async_ingest_youtube_url(url: str, console: bool, dry_run: bool):
    """Async implementation of single YouTube URL ingestion."""
    writer = None
    if not dry_run:
        writer = await _make_writer()

    try:
        count = ingest_youtube_url(writer=writer, url=url, console=console, dry_run=dry_run)
        print(f"[green]OK[/green] Processed {count} video(s)")
    except FatalIngestionError as exc:
        print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=5)
    finally:
        if writer and isinstance(writer, DatabaseWriter):
            await writer.close()


@app.command("migrate")
def cmd_migrate(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Migrate all content from Notion to SQLite database.

    This command exports all videos, articles, and logs from Notion and imports
    them into the local SQLite database. The migration is idempotent and can be
    run multiple times safely.

    WARNING: This requires NOTION_TOKEN to be set and will make many API calls.
    """
    asyncio.run(_async_migrate(yes))


async def _async_migrate(yes: bool):
    """Async implementation of migration command."""
    from .migrate_from_notion import main as migrate_main

    # Check for Notion token
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        print("Migration requires access to Notion to export data.")
        raise typer.Exit(code=1)

    # Check Notion config
    notion_config = load_notion_config()
    if not notion_config.youtube_db_id or not notion_config.articles_db_id or not notion_config.log_db_id:
        print("[red]ERROR[/red]: Notion database IDs not found in config/notion.json")
        print("Run 'nexus notion --parent-page-id <id>' first to bootstrap Notion databases")
        raise typer.Exit(code=2)

    # Confirmation prompt
    if not yes:
        print("[bold yellow]Migration: Notion → SQLite[/bold yellow]\n")
        print("This will:")
        print("  1. Export all videos, articles, and logs from Notion")
        print("  2. Import them into db/nexus.sqlite")
        print("  3. Preserve existing SQLite data (upsert only)")
        print("\n[yellow]Note:[/yellow] This may take several minutes and will make many Notion API calls.\n")

        confirm = typer.confirm("Do you want to proceed?")
        if not confirm:
            print("Migration cancelled.")
            raise typer.Exit(code=0)

    # Run migration
    await migrate_main()


def main():
    app()


if __name__ == "__main__":
    main()


