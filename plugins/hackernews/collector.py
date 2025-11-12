"""Collect top stories from Hacker News using the official Firebase API."""

from __future__ import annotations

import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional


@dataclass
class HNStory:
    """Represents a Hacker News story."""
    id: int
    title: str
    url: str
    score: int
    time: datetime
    by: str
    hn_url: str  # Link to HN discussion


async def fetch_top_stories(min_score: int = 100, since_hours: int = 24) -> list[HNStory]:
    """
    Fetch HN stories with score >= min_score from the last N hours.

    Uses the official HackerNews Firebase API:
    - /v0/topstories.json - Returns list of story IDs sorted by rank
    - /v0/item/{id}.json - Returns story details

    Args:
        min_score: Minimum score threshold (default 100)
        since_hours: How many hours to look back (default 24)

    Returns:
        List of HNStory objects matching criteria
    """
    base_url = "https://hacker-news.firebaseio.com/v0"

    # Fetch top story IDs (already sorted by rank)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{base_url}/topstories.json", timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                story_ids = await response.json()
        except Exception as e:
            print(f"[HN] Error fetching top stories: {e}")
            return []

        # Calculate cutoff time
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)

        # Fetch details for first 100 stories in parallel
        max_to_check = 100  # Only check first 100 stories to avoid excessive API calls
        story_ids_to_check = story_ids[:max_to_check]

        # Fetch all story details in parallel
        tasks = [_fetch_story_detail(session, base_url, story_id, min_score, cutoff_time) for story_id in story_ids_to_check]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out None values and exceptions
        stories = [story for story in results if isinstance(story, HNStory)]

        print(f"[HN] Checked {len(story_ids_to_check)} stories, found {len(stories)} matching criteria (score >= {min_score}, last {since_hours}h)")
        return stories


async def _fetch_story_detail(
    session: aiohttp.ClientSession,
    base_url: str,
    story_id: int,
    min_score: int,
    cutoff_time: datetime
) -> Optional[HNStory]:
    """Fetch and validate a single story. Returns None if story doesn't meet criteria."""
    try:
        async with session.get(f"{base_url}/item/{story_id}.json", timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            item = await response.json()

            if not item or item.get("type") != "story":
                return None

            # Skip if no URL (Ask HN, Show HN without link, etc.)
            if not item.get("url"):
                return None

            # Parse timestamp
            story_time = datetime.fromtimestamp(item["time"], tz=timezone.utc)

            # Check if story meets criteria
            score = item.get("score", 0)

            # Skip if too old
            if story_time < cutoff_time:
                return None

            # Skip if score too low
            if score < min_score:
                return None

            # Create story object
            return HNStory(
                id=story_id,
                title=item.get("title", "Untitled"),
                url=item["url"],
                score=score,
                time=story_time,
                by=item.get("by", "unknown"),
                hn_url=f"https://news.ycombinator.com/item?id={story_id}",
            )

    except Exception as e:
        print(f"[HN] Error fetching story {story_id}: {e}")
        return None
