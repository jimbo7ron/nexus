from __future__ import annotations

import asyncio
from typing import Dict, Optional

from notion_client import Client

from tools.rate_limiter import RateLimiter
from tools.text_utils import safe_truncate


def build_youtube_properties() -> Dict:
    """YouTube database schema for video content."""
    return {
        "Name": {"title": {}},  # Notion's default title property
        "Link": {"url": {}},
        "Thumbnail": {"files": {}},  # External file/image URL
        "Summary": {"rich_text": {}},
        "Source": {"rich_text": {}},
        "Published": {"date": {}},
        "Last Updated": {"date": {}},
    }


def build_articles_properties() -> Dict:
    """Articles database schema for news articles and blog posts."""
    return {
        "Name": {"title": {}},  # Notion's default title property
        "Link": {"url": {}},
        "Summary": {"rich_text": {}},
        "Body": {"rich_text": {}},
        "Source": {"rich_text": {}},
        "Published": {"date": {}},
        "Last Updated": {"date": {}},
    }


def build_log_properties() -> Dict:
    return {
        "Name": {"title": {}},  # Every database needs a title property
        "Time": {"date": {}},
        "Item URL": {"url": {}},
        "Action": {"select": {"options": [{"name": n} for n in ["discover", "fetch", "summarize", "write"]]}},
        "Result": {"select": {"options": [{"name": n} for n in ["ok", "skip", "error"]]}},
        "Message": {"rich_text": {}},
    }


async def ensure_database(
    client: Client,
    parent_page_id: str,
    existing_db_id: str,
    name: str,
    properties: Dict,
) -> str:
    if existing_db_id:
        return existing_db_id

    # The Python notion-client library has a bug where it doesn't pass properties correctly.
    # Use raw HTTP request instead to create database with properties.
    import aiohttp
    import os

    token = os.getenv("NOTION_TOKEN")
    if not token:
        # Fallback: try to get token from client (this is hacky but works)
        token = client.options.get("auth")

    url = "https://api.notion.com/v1/databases"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": name}}],
        "properties": properties,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            response.raise_for_status()
            result = await response.json()

    return result["id"]


class NotionWriter:
    def __init__(
        self,
        client: Client,
        youtube_db_id: str,
        articles_db_id: str,
        log_db_id: str,
    ):
        self.client = client
        self.youtube_db_id = youtube_db_id
        self.articles_db_id = articles_db_id
        self.log_db_id = log_db_id
        # Rate limit: 3 requests per second for Notion API
        self.rate_limiter = RateLimiter(rate=3, period=1.0)
        # Lock to serialize access to the Notion client (not thread-safe)
        # Note: Lock will be created lazily in the correct event loop
        self._lock = None

    def _get_lock(self):
        """Get or create lock in current event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _find_page_by_link(self, database_id: str, url: str) -> Optional[str]:
        """Find a page in a database by its Link (URL) field."""
        try:
            await self.rate_limiter.acquire()
            # Query the database for pages with matching URL using direct API request
            # Use sync call within lock - Notion client is fast and we're rate-limited anyway
            # Normalize database_id: remove dashes for API path
            normalized_db_id = database_id.replace("-", "")
            async with self._get_lock():
                response = self.client.request(
                    path=f"databases/{normalized_db_id}/query",
                    method="POST",
                    body={
                        "filter": {"property": "Link", "url": {"equals": url}},
                        "page_size": 1,
                    }
                )
                await asyncio.sleep(0)  # Yield control to event loop
            results = response.get("results", [])
            if results:
                return results[0]["id"]
        except Exception as e:
            # If query fails, just return None and create a new page
            print(f"Warning: Could not query database: {e}")
        return None

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
        """Upsert video to YouTube database."""
        page_id = await self._find_page_by_link(self.youtube_db_id, url)

        props = {
            "Name": {"title": [{"type": "text", "text": {"content": safe_truncate(title, 200)}}]},
            "Link": {"url": url},
            "Summary": {"rich_text": [{"type": "text", "text": {"content": safe_truncate(summary, 2000)}}] if summary else []},
            "Source": {"rich_text": [{"type": "text", "text": {"content": safe_truncate(source, 200)}}] if source else []},
            "Published": {"date": {"start": published_iso}} if published_iso else {"date": None},
            "Last Updated": {"date": {"start": last_updated_iso}} if last_updated_iso else {"date": None},
        }

        # Add thumbnail if provided and property exists
        # TODO: Re-enable once Notion database schema is confirmed
        # if thumbnail:
        #     props["Thumbnail"] = {"files": [{"type": "external", "name": "Thumbnail", "external": {"url": thumbnail}}]}

        await self.rate_limiter.acquire()
        async with self._get_lock():
            if page_id:
                self.client.pages.update(page_id=page_id, properties=props)
                await asyncio.sleep(0)
                return page_id
            created = self.client.pages.create(
                parent={"database_id": self.youtube_db_id},
                properties=props,
            )
            await asyncio.sleep(0)
        return created["id"]

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
        """Upsert article to Articles database."""
        page_id = await self._find_page_by_link(self.articles_db_id, url)

        props = {
            "Name": {"title": [{"type": "text", "text": {"content": safe_truncate(title, 200)}}]},
            "Link": {"url": url},
            "Summary": {"rich_text": [{"type": "text", "text": {"content": safe_truncate(summary, 2000)}}] if summary else []},
            "Body": {"rich_text": [{"type": "text", "text": {"content": safe_truncate(body, 2000)}}] if body else []},
            "Source": {"rich_text": [{"type": "text", "text": {"content": safe_truncate(source, 200)}}] if source else []},
            "Published": {"date": {"start": published_iso}} if published_iso else {"date": None},
            "Last Updated": {"date": {"start": last_updated_iso}} if last_updated_iso else {"date": None},
        }

        await self.rate_limiter.acquire()
        async with self._get_lock():
            if page_id:
                self.client.pages.update(page_id=page_id, properties=props)
                await asyncio.sleep(0)
                return page_id
            created = self.client.pages.create(
                parent={"database_id": self.articles_db_id},
                properties=props,
            )
            await asyncio.sleep(0)
        return created["id"]

    async def log_event(self, item_url: str, action: str, result: str, message: str = "", when_iso: Optional[str] = None) -> str:
        from datetime import datetime, timezone

        # Auto-generate timestamp if not provided
        if not when_iso:
            when_iso = datetime.now(timezone.utc).isoformat()

        props = {
            "Name": {"title": [{"type": "text", "text": {"content": safe_truncate(f"{action} | {result}", 100)}}]},
            "Time": {"date": {"start": when_iso}},
            "Item URL": {"url": item_url},
            "Action": {"select": {"name": action}},
            "Result": {"select": {"name": result}},
            "Message": {"rich_text": [{"type": "text", "text": {"content": safe_truncate(message, 2000)}}] if message else []},
        }
        await self.rate_limiter.acquire()
        async with self._get_lock():
            created = self.client.pages.create(
                parent={"database_id": self.log_db_id},
                properties=props
            )
            await asyncio.sleep(0)
        return created["id"]
