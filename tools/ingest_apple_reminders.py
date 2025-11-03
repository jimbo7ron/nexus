from __future__ import annotations

from datetime import datetime, timezone

from notion_client import Client

from .config import load_apple_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.apple.reminders import fetch_reminders_from_list
from .storage import has_changed, mark_processed


def ingest_apple_reminders(
    client: Client,
    writer: NotionWriter,
    console: bool = False,
) -> int:
    cfg = load_apple_config()
    lst = cfg.get("reminders_list", "Nexus")
    items = fetch_reminders_from_list(lst)
    total = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in items:
        url = f"reminders://{item.reminder_id}"
        base = f"{item.title}|{item.list_name}|{item.due or ''}"
        content_hash_val = content_hash(base)
        if not has_changed(url, content_hash_val):
            writer.log_event(url, action="fetch", result="skip", message="unchanged")
            continue
        if console:
            print(f"[Reminder] {item.title or '(untitled)'} | {url}\nList: {item.list_name}  Due: {item.due or ''}")
        writer.upsert_reminder(
            title=item.title or "(untitled)",
            url=url,
            body="",
            source=item.list_name,
            due_date_iso=item.due,
            last_updated_iso=now_iso,
        )
        writer.log_event(url, action="write", result="ok", message="reminder upserted")
        mark_processed(url, content_hash_val)
        total += 1
    return total


