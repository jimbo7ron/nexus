from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Suppress known warnings for Python 3.9 and LibreSSL
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core._python_version_support")
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import typer
from notion_client import Client
from rich import print

from .config import load_notion_config, save_notion_config, get_notion_token
from .notion import (
    build_youtube_properties,
    build_articles_properties,
    build_notes_properties,
    build_reminders_properties,
    build_log_properties,
    ensure_database,
    NotionWriter,
)
from .ingest_youtube import ingest_youtube_since
from .ingest_news import ingest_news_since
from .ingest_hackernews import ingest_hackernews
from .ingest_apple_notes import ingest_apple_notes
from .ingest_apple_reminders import ingest_apple_reminders
from .ingest_youtube import ingest_youtube_url


app = typer.Typer(help="Nexus CLI")


@app.command("notion")
def notion_bootstrap(
    parent_page_id: str = typer.Option(
        "",
        help="Notion parent page ID. If omitted, uses config/notion.json parent_page_id",
    )
):
    """Ensure Content and Ingestion Log databases exist in Notion and save their IDs in config."""
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
    youtube_id = ensure_database(
        client,
        cfg.parent_page_id,
        cfg.youtube_db_id,
        name="YouTube",
        properties=build_youtube_properties(),
    )
    # Ensure Articles DB (news articles and blog posts)
    articles_id = ensure_database(
        client,
        cfg.parent_page_id,
        cfg.articles_db_id,
        name="Articles",
        properties=build_articles_properties(),
    )
    # Ensure Notes DB
    notes_id = ensure_database(
        client,
        cfg.parent_page_id,
        cfg.notes_db_id,
        name="Notes",
        properties=build_notes_properties(),
    )
    # Ensure Reminders DB
    reminders_id = ensure_database(
        client,
        cfg.parent_page_id,
        cfg.reminders_db_id,
        name="Reminders",
        properties=build_reminders_properties(),
    )
    # Ensure Ingestion Log DB
    log_id = ensure_database(
        client,
        cfg.parent_page_id,
        cfg.log_db_id,
        name="Ingestion Log",
        properties=build_log_properties(),
    )

    cfg.youtube_db_id = youtube_id
    cfg.articles_db_id = articles_id
    cfg.notes_db_id = notes_id
    cfg.reminders_db_id = reminders_id
    cfg.log_db_id = log_id
    save_notion_config(cfg)

    print("[green]OK[/green] Notion databases ensured.")
    print(f"YouTube DB ID: [bold]{youtube_id}[/bold]")
    print(f"Articles DB ID: [bold]{articles_id}[/bold]")
    print(f"Notes DB ID: [bold]{notes_id}[/bold]")
    print(f"Reminders DB ID: [bold]{reminders_id}[/bold]")
    print(f"Ingestion Log DB ID: [bold]{log_id}[/bold]")


def _make_writer(token: str) -> NotionWriter:
    cfg = load_notion_config()
    if not cfg.youtube_db_id or not cfg.articles_db_id or not cfg.notes_db_id or not cfg.reminders_db_id or not cfg.log_db_id:
        print("[red]ERROR[/red]: Notion DB IDs missing. Run `nexus notion` first.")
        raise typer.Exit(code=3)
    client = Client(auth=token)
    
    # Validate databases exist
    try:
        client.databases.retrieve(database_id=cfg.youtube_db_id)
        client.databases.retrieve(database_id=cfg.articles_db_id)
        client.databases.retrieve(database_id=cfg.notes_db_id)
        client.databases.retrieve(database_id=cfg.reminders_db_id)
        client.databases.retrieve(database_id=cfg.log_db_id)
    except Exception as e:
        print(f"[red]ERROR[/red]: Could not access Notion databases. Run `nexus notion` to recreate them.")
        print(f"Details: {str(e)}")
        raise typer.Exit(code=4)
    
    return NotionWriter(client, cfg.youtube_db_id, cfg.articles_db_id, cfg.notes_db_id, cfg.reminders_db_id, cfg.log_db_id)


@app.command("ingest-youtube")
def cmd_ingest_youtube(
    since: int = typer.Option(24, help="Hours back to check"),
    console: bool = typer.Option(False, "--console", help="Print items to console as they are processed"),
):
    """Ingest YouTube videos from RSS feeds configured in config/feeds.yaml."""
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        raise typer.Exit(code=1)
    writer = _make_writer(token)
    client = writer.client
    count = ingest_youtube_since(client, writer, since_hours=since, console=console)
    print(f"[green]OK[/green] Ingested {count} YouTube items")


@app.command("ingest-news")
def cmd_ingest_news(
    since: int = typer.Option(24, help="Hours back to check"),
    console: bool = typer.Option(False, "--console", help="Print items to console as they are processed"),
):
    """Ingest news articles from RSS feeds configured in config/feeds.yaml."""
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        raise typer.Exit(code=1)
    writer = _make_writer(token)
    client = writer.client
    count = ingest_news_since(client, writer, since_hours=since, console=console)
    print(f"[green]OK[/green] Ingested {count} articles")


@app.command("ingest-hackernews")
def cmd_ingest_hackernews(
    min_score: int = typer.Option(100, "--min-score", help="Minimum HN score threshold"),
    since: int = typer.Option(24, "--since", help="Hours to look back"),
    console: bool = typer.Option(False, "--console", help="Print items to console as they are processed"),
):
    """Ingest high-scoring Hacker News stories (default: 100+ points, last 24h)."""
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        raise typer.Exit(code=1)
    writer = _make_writer(token)
    client = writer.client
    count = ingest_hackernews(client, writer, min_score=min_score, since_hours=since, console=console)
    print(f"[green]OK[/green] Ingested {count} HN stories")


@app.command("ingest-apple-notes")
def cmd_ingest_apple_notes(
    console: bool = typer.Option(False, "--console", help="Print items to console as they are processed"),
):
    """Ingest Apple Notes from folder configured in config/apple.yaml."""
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        raise typer.Exit(code=1)
    writer = _make_writer(token)
    client = writer.client
    count = ingest_apple_notes(client, writer, console=console)
    print(f"[green]OK[/green] Ingested {count} notes")


@app.command("ingest-apple-reminders")
def cmd_ingest_apple_reminders(
    console: bool = typer.Option(False, "--console", help="Print items to console as they are processed"),
):
    """Ingest Apple Reminders from list configured in config/apple.yaml."""
    token = get_notion_token()
    if not token:
        print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set.")
        raise typer.Exit(code=1)
    writer = _make_writer(token)
    client = writer.client
    count = ingest_apple_reminders(client, writer, console=console)
    print(f"[green]OK[/green] Ingested {count} reminders")


@app.command("ingest-youtube-url")
def cmd_ingest_youtube_url(
    url: str = typer.Option(..., "--url", help="YouTube video URL"),
    console: bool = typer.Option(False, "--console", help="Print transcript preview to console"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write to Notion; console only"),
):
    """Ingest a single YouTube video by URL, with transcript and summary."""
    token = get_notion_token()
    writer = None
    if not dry_run:
        if not token:
            print("[red]ERROR[/red]: NOTION_TOKEN environment variable is not set. Use --dry-run to skip Notion.")
            raise typer.Exit(code=1)
        writer = _make_writer(token)

    count = ingest_youtube_url(writer=writer, url=url, console=console, dry_run=dry_run)
    print(f"[green]OK[/green] Processed {count} video(s)")


def main():
    app()


if __name__ == "__main__":
    main()


