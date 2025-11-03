from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

import feedparser


@dataclass
class ArticleItem:
    url: str
    title: str
    published: datetime | None
    site: str | None


def _parse_published(entry) -> datetime | None:
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def discover_feed(feed_url: str, since_hours: int = 24) -> List[ArticleItem]:
    feed = feedparser.parse(feed_url)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    site = getattr(getattr(feed, "feed", {}), "title", None)
    items: List[ArticleItem] = []
    for e in feed.entries:
        link = getattr(e, "link", None)
        title = getattr(e, "title", None)
        published = _parse_published(e)
        if not link:
            continue
        if published and published < cutoff:
            continue
        items.append(ArticleItem(url=link, title=title or link, published=published, site=site))
    return items


