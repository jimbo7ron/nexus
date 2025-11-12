from __future__ import annotations

import asyncio
from typing import Optional

import trafilatura


async def fetch_article_text(url: str) -> Optional[str]:
    """Fetch and extract article text from URL using trafilatura (wrapped in thread pool)."""
    downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
    if not downloaded:
        return None
    text = await asyncio.to_thread(trafilatura.extract, downloaded, include_comments=False, include_tables=False)
    return text
