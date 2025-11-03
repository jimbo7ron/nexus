from __future__ import annotations

from datetime import datetime, timezone

from notion_client import Client

from .config import load_apple_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.apple.notes import fetch_notes_from_folder
from .storage import has_changed, mark_processed


def ingest_apple_notes(
    client: Client,
    writer: NotionWriter,
    console: bool = False,
) -> int:
    cfg = load_apple_config()
    folder = cfg.get("notes_folder", "Nexus")
    items = fetch_notes_from_folder(folder)
    total = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in items:
        url = f"notes://{item.note_id}"
        content_hash_val = content_hash(item.title + "\n" + item.body)
        if not has_changed(url, content_hash_val):
            writer.log_event(url, action="fetch", result="skip", message="unchanged")
            continue
        if console:
            preview = (item.body[:500] or "").replace("\n", " ")
            print(f"[Note] {item.title or '(untitled)'} | {url}\nFolder: {item.folder}\nPreview: {preview}...")
        writer.upsert_note(
            title=item.title or "(untitled)",
            url=url,
            body=item.body,
            source=item.folder,
            last_updated_iso=now_iso,
        )
        writer.log_event(url, action="write", result="ok", message="note upserted")
        mark_processed(url, content_hash_val)
        total += 1
    return total


