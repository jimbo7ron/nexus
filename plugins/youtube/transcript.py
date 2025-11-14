from __future__ import annotations

import asyncio
import warnings
from typing import List, Optional

# Suppress Python 3.9 deprecation warning from youtube-transcript-api
warnings.filterwarnings("ignore", message=".*Support for Python version 3.9 has been deprecated.*")

from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url_or_id: str) -> str:
    if len(url_or_id) == 11 and "/" not in url_or_id:
        return url_or_id
    # crude extraction for common formats; sufficient for MVP
    if "v=" in url_or_id:
        return url_or_id.split("v=")[-1].split("&")[0]
    if "/shorts/" in url_or_id:
        return url_or_id.split("/shorts/")[-1].split("?")[0]
    if "/watch/" in url_or_id:
        return url_or_id.split("/watch/")[-1].split("?")[0]
    if "/embed/" in url_or_id:
        return url_or_id.split("/embed/")[-1].split("?")[0]
    if "/" in url_or_id:
        last = url_or_id.rstrip("/").split("/")[-1]
        if "?" in last:
            last = last.split("?")[0]
        return last
    return url_or_id


def fetch_transcript_text(url_or_id: str, languages: Optional[List[str]] = None) -> str:
    vid = extract_video_id(url_or_id)
    langs = tuple(languages or ["en", "en-US"])
    api = YouTubeTranscriptApi()
    segments = api.fetch(vid, languages=langs)
    parts = []
    for s in segments:
        text = s.get("text") if hasattr(s, "get") else getattr(s, "text", "")
        if text:
            parts.append(text)
    return "\n".join(parts)


async def fetch_transcript_text_async(url_or_id: str, languages: Optional[List[str]] = None) -> str:
    """Async wrapper for transcript fetching using thread pool."""
    return await asyncio.to_thread(fetch_transcript_text, url_or_id, languages)


