from __future__ import annotations

from typing import Dict, Optional

from notion_client import Client


def build_youtube_properties() -> Dict:
    """YouTube database schema for video content."""
    return {
        "Name": {"title": {}},  # Notion's default title property
        "Link": {"url": {}},
        "Thumbnail": {"url": {}},
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


def build_notes_properties() -> Dict:
    """Notes database schema for Apple Notes."""
    return {
        "Name": {"title": {}},
        "Link": {"url": {}},
        "Body": {"rich_text": {}},
        "Source": {"rich_text": {}},
        "Last Updated": {"date": {}},
    }


def build_reminders_properties() -> Dict:
    """Reminders database schema for Apple Reminders."""
    return {
        "Name": {"title": {}},
        "Link": {"url": {}},
        "Body": {"rich_text": {}},
        "Source": {"rich_text": {}},
        "Due Date": {"date": {}},
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


def ensure_database(
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
    import requests
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
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    result = response.json()
    
    return result["id"]


class NotionWriter:
    def __init__(
        self,
        client: Client,
        youtube_db_id: str,
        articles_db_id: str,
        notes_db_id: str,
        reminders_db_id: str,
        log_db_id: str,
    ):
        self.client = client
        self.youtube_db_id = youtube_db_id
        self.articles_db_id = articles_db_id
        self.notes_db_id = notes_db_id
        self.reminders_db_id = reminders_db_id
        self.log_db_id = log_db_id

    def _find_page_by_link(self, database_id: str, url: str) -> Optional[str]:
        """Find a page in a database by its Link (URL) field."""
        try:
            # Query the database for pages with matching URL using raw request
            response = self.client.request(
                path=f"databases/{database_id}/query",
                method="POST",
                body={
                    "filter": {"property": "Link", "url": {"equals": url}},
                    "page_size": 1,
                },
            )
            results = response.get("results", [])
            if results:
                return results[0]["id"]
        except Exception as e:
            # If query fails, just return None and create a new page
            print(f"Warning: Could not query database: {e}")
        return None

    def upsert_video(
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
        page_id = self._find_page_by_link(self.youtube_db_id, url)
        
        props = {
            "Name": {"title": [{"type": "text", "text": {"content": title[:200]}}]},
            "Link": {"url": url},
            "Thumbnail": {"url": thumbnail} if thumbnail else {"url": None},
            "Summary": {"rich_text": [{"type": "text", "text": {"content": summary[:2000]}}] if summary else []},
            "Source": {"rich_text": [{"type": "text", "text": {"content": source[:200]}}] if source else []},
            "Published": {"date": {"start": published_iso}} if published_iso else {"date": None},
            "Last Updated": {"date": {"start": last_updated_iso}} if last_updated_iso else {"date": None},
        }
        
        if page_id:
            self.client.pages.update(page_id=page_id, properties=props)
            return page_id
        created = self.client.pages.create(
            parent={"database_id": self.youtube_db_id},
            properties=props,
        )
        return created["id"]

    def upsert_article(
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
        page_id = self._find_page_by_link(self.articles_db_id, url)
        
        props = {
            "Name": {"title": [{"type": "text", "text": {"content": title[:200]}}]},
            "Link": {"url": url},
            "Summary": {"rich_text": [{"type": "text", "text": {"content": summary[:2000]}}] if summary else []},
            "Body": {"rich_text": [{"type": "text", "text": {"content": body[:2000]}}] if body else []},
            "Source": {"rich_text": [{"type": "text", "text": {"content": source[:200]}}] if source else []},
            "Published": {"date": {"start": published_iso}} if published_iso else {"date": None},
            "Last Updated": {"date": {"start": last_updated_iso}} if last_updated_iso else {"date": None},
        }
        
        if page_id:
            self.client.pages.update(page_id=page_id, properties=props)
            return page_id
        created = self.client.pages.create(
            parent={"database_id": self.articles_db_id},
            properties=props,
        )
        return created["id"]

    def upsert_note(
        self,
        title: str,
        url: str,
        body: str = "",
        source: str = "",
        last_updated_iso: Optional[str] = None,
    ) -> str:
        """Upsert note to Notes database."""
        page_id = self._find_page_by_link(self.notes_db_id, url)
        props = {
            "Title": {"title": [{"type": "text", "text": {"content": title[:200]}}]},
            "Link": {"url": url},
            "Body": {"rich_text": [{"type": "text", "text": {"content": body[:2000]}}] if body else []},
            "Source": {"rich_text": [{"type": "text", "text": {"content": source[:200]}}] if source else []},
            "Last Updated": {"date": {"start": last_updated_iso}} if last_updated_iso else {"date": None},
        }
        if page_id:
            self.client.pages.update(page_id=page_id, properties=props)
            return page_id
        created = self.client.pages.create(
            parent={"database_id": self.notes_db_id},
            properties=props,
        )
        return created["id"]

    def upsert_reminder(
        self,
        title: str,
        url: str,
        body: str = "",
        source: str = "",
        due_date_iso: Optional[str] = None,
        last_updated_iso: Optional[str] = None,
    ) -> str:
        """Upsert reminder to Reminders database."""
        page_id = self._find_page_by_link(self.reminders_db_id, url)
        props = {
            "Title": {"title": [{"type": "text", "text": {"content": title[:200]}}]},
            "Link": {"url": url},
            "Body": {"rich_text": [{"type": "text", "text": {"content": body[:200]}}] if body else []},
            "Source": {"rich_text": [{"type": "text", "text": {"content": source[:200]}}] if source else []},
            "Due Date": {"date": {"start": due_date_iso}} if due_date_iso else {"date": None},
            "Last Updated": {"date": {"start": last_updated_iso}} if last_updated_iso else {"date": None},
        }
        if page_id:
            self.client.pages.update(page_id=page_id, properties=props)
            return page_id
        created = self.client.pages.create(
            parent={"database_id": self.reminders_db_id},
            properties=props,
        )
        return created["id"]

    def log_event(self, item_url: str, action: str, result: str, message: str = "", when_iso: Optional[str] = None) -> str:
        from datetime import datetime, timezone
        
        # Auto-generate timestamp if not provided
        if not when_iso:
            when_iso = datetime.now(timezone.utc).isoformat()
        
        props = {
            "Name": {"title": [{"type": "text", "text": {"content": f"{action} | {result}"[:100]}}]},
            "Time": {"date": {"start": when_iso}},
            "Item URL": {"url": item_url},
            "Action": {"select": {"name": action}},
            "Result": {"select": {"name": result}},
            "Message": {"rich_text": [{"type": "text", "text": {"content": message}}] if message else []},
        }
        created = self.client.pages.create(parent={"database_id": self.log_db_id}, properties=props)
        return created["id"]


