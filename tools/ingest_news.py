from __future__ import annotations

from datetime import datetime, timezone

from notion_client import Client

from .config import load_feeds_config, load_summarize_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.news.collector import discover_feed
from plugins.news.extractor import fetch_article_text
from .summarizer import Summarizer
from .storage import has_changed, mark_processed


def ingest_news_since(
    client: Client,
    writer: NotionWriter,
    since_hours: int = 24,
    console: bool = False,
) -> int:
    feeds = load_feeds_config()
    rss_feeds = feeds.get("rss_feeds", []) or []
    summarizer = Summarizer(load_summarize_config())
    total = 0
    for feed_url in rss_feeds:
        items = discover_feed(feed_url, since_hours=since_hours)
        for item in items:
            text = fetch_article_text(item.url)
            if not text:
                writer.log_event(item.url, action="fetch", result="error", message="no content")
                continue
            content_hash_val = content_hash(text)
            now_iso = datetime.now(timezone.utc).isoformat()
            if not has_changed(item.url, content_hash_val):
                writer.log_event(item.url, action="fetch", result="skip", message="unchanged")
                continue
            
            # Summarize
            try:
                summary_obj = summarizer.summarize_article(item.title, item.site, text)
                # Combine summary, takeaways, and key quotes into one Summary field
                summary_parts = [f"TL;DR: {summary_obj.tldr}", "", "Takeaways:"]
                summary_parts.extend([f"- {t}" for t in summary_obj.takeaways])
                if summary_obj.key_quotes:
                    summary_parts.extend(["", "Key Quotes:"])
                    summary_parts.extend([f"- {q}" for q in summary_obj.key_quotes])
                summary_text = "\n".join(summary_parts)
            except Exception as e:
                # Fallback: store truncated text
                summary_text = text[:2000]
                writer.log_event(item.url, action="summarize", result="error", message=str(e))
            
            if console:
                preview = (text[:500] or "").replace("\n", " ")
                print(f"[Article] {item.title} | {item.url}\nSite: {item.site or ''}\nPublished: {item.published or ''}\nContent preview: {preview}...")
            
            writer.upsert_article(
                title=item.title,
                url=item.url,
                summary=summary_text,
                body=text,
                source=item.site or "",
                published_iso=item.published.isoformat() if item.published else None,
                last_updated_iso=now_iso,
            )
            writer.log_event(item.url, action="write", result="ok", message="article upserted")
            mark_processed(item.url, content_hash_val)
            total += 1
    return total


