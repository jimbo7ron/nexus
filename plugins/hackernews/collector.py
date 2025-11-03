"""Collect top stories from Hacker News using the official Firebase API."""

from __future__ import annotations

import requests
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


def fetch_top_stories(min_score: int = 100, since_hours: int = 24) -> list[HNStory]:
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
    try:
        response = requests.get(f"{base_url}/topstories.json", timeout=10)
        response.raise_for_status()
        story_ids = response.json()
    except Exception as e:
        print(f"[HN] Error fetching top stories: {e}")
        return []
    
    # Calculate cutoff time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    
    # Fetch details for each story until we have enough or run out
    stories = []
    checked = 0
    max_to_check = 100  # Only check first 100 stories to avoid excessive API calls
    
    for story_id in story_ids[:max_to_check]:
        checked += 1
        
        try:
            response = requests.get(f"{base_url}/item/{story_id}.json", timeout=5)
            response.raise_for_status()
            item = response.json()
            
            if not item or item.get("type") != "story":
                continue
            
            # Skip if no URL (Ask HN, Show HN without link, etc.)
            if not item.get("url"):
                continue
            
            # Parse timestamp
            story_time = datetime.fromtimestamp(item["time"], tz=timezone.utc)
            
            # Check if story meets criteria
            score = item.get("score", 0)
            
            # Skip if too old
            if story_time < cutoff_time:
                # Since stories are sorted by rank (not time), we can't stop early
                # but we can skip old stories
                continue
            
            # Skip if score too low
            if score < min_score:
                continue
            
            # Create story object
            story = HNStory(
                id=story_id,
                title=item.get("title", "Untitled"),
                url=item["url"],
                score=score,
                time=story_time,
                by=item.get("by", "unknown"),
                hn_url=f"https://news.ycombinator.com/item?id={story_id}",
            )
            
            stories.append(story)
            
        except Exception as e:
            print(f"[HN] Error fetching story {story_id}: {e}")
            continue
    
    print(f"[HN] Checked {checked} stories, found {len(stories)} matching criteria (score >= {min_score}, last {since_hours}h)")
    return stories

