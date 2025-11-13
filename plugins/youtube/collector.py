from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

import feedparser


YOUTUBE_CHANNEL_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_PLAYLIST_RSS = "https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"


@dataclass
class VideoItem:
    url: str
    title: str
    published: datetime | None
    channel: str | None
    video_id: str | None


def _parse_published(entry) -> datetime | None:
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    except Exception:
        return None
    return None


_executor: ThreadPoolExecutor | None = None
_EXECUTOR_WORKERS = 8


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_EXECUTOR_WORKERS, thread_name_prefix="yt-collector")
    return _executor


async def shutdown_collector_executor() -> None:
    """Shutdown the shared executor used for blocking YouTube calls."""
    global _executor
    if _executor is not None:
        executor = _executor
        _executor = None
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


def discover_channel(channel_id: str, since_hours: int = 24) -> List[VideoItem]:
    """Discover videos from a specific channel RSS feed."""
    url = YOUTUBE_CHANNEL_RSS.format(channel_id=channel_id)
    return _discover_feed(url, since_hours)


def discover_feed(feed_url: str, since_hours: int = 24) -> List[VideoItem]:
    """Discover videos from any YouTube RSS feed URL (channel, playlist, or subscriptions)."""
    return _discover_feed(feed_url, since_hours)


class DiscoveryError(Exception):
    """Raised when discovery fails for a channel/feed."""


def _discover_feed(url: str, since_hours: int) -> List[VideoItem]:
    """Parse a YouTube RSS feed and return recent videos."""
    feed = feedparser.parse(url)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    items: List[VideoItem] = []
    for e in feed.entries:
        link = getattr(e, "link", None)
        title = getattr(e, "title", None)
        published = _parse_published(e)
        channel = getattr(getattr(feed, "feed", {}), "author", None) or getattr(e, "author", None)
        vid = getattr(e, "yt_videoid", None) or getattr(e, "yt_video_id", None)
        if not link:
            continue
        if published and published < cutoff:
            continue
        items.append(VideoItem(url=link, title=title or link, published=published, channel=channel, video_id=vid))
    return items


def discover_subscriptions_via_api(
    since_hours: int = 24,
    max_channels: int = 50,
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
) -> List[VideoItem]:
    """Discover videos from all subscribed channels using YouTube Data API.
    
    This function:
    1. Authenticates with YouTube API (OAuth2)
    2. Fetches all channel IDs you're subscribed to
    3. Gets recent videos from each channel via RSS
    
    Args:
        since_hours: Only return videos published within this many hours
        max_channels: Maximum number of subscribed channels to fetch
        client_secret_path: Path to OAuth client secret JSON
        token_path: Path to store authentication token
    
    Returns:
        List of VideoItem objects from all subscriptions
    """
    from .api_client import YouTubeAPIClient
    
    # Initialize and authenticate
    client = YouTubeAPIClient(client_secret_path=client_secret_path, token_path=token_path)
    
    # Get all subscribed channel IDs
    print(f"[YouTube API] Fetching subscriptions (max {max_channels})...")
    channel_ids = client.get_subscription_channel_ids(max_results=max_channels)
    print(f"[YouTube API] Found {len(channel_ids)} subscriptions")
    
    # Collect videos from all channels
    all_videos: List[VideoItem] = []
    for i, channel_id in enumerate(channel_ids, 1):
        print(f"[YouTube API] Fetching videos from channel {i}/{len(channel_ids)}: {channel_id}")
        try:
            videos = discover_channel(channel_id, since_hours=since_hours)
            all_videos.extend(videos)
            print(f"  → Found {len(videos)} recent video(s)")
        except Exception as e:
            print(f"  → Error fetching channel {channel_id}: {e}")
    
    # Sort by published date (newest first)
    all_videos.sort(key=lambda v: v.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    print(f"[YouTube API] Total videos discovered: {len(all_videos)}")
    return all_videos


# Async wrappers for parallel processing

async def discover_channel_async(channel_id: str, since_hours: int = 24) -> List[VideoItem]:
    """Async wrapper for discover_channel."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), discover_channel, channel_id, since_hours)


async def discover_feed_async(feed_url: str, since_hours: int = 24) -> List[VideoItem]:
    """Async wrapper for discover_feed."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), discover_feed, feed_url, since_hours)


async def discover_subscriptions_via_api_async(
    since_hours: int = 24,
    max_channels: int = 50,
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
    max_concurrency: int = 10,
) -> List[VideoItem]:
    """Async version of discover_subscriptions_via_api with parallel channel fetching."""
    from .api_client import YouTubeAPIClient

    # Wrap API client operations in thread pool (OAuth happens here)
    print(f"[YouTube API] Fetching subscriptions (max {max_channels})...")
    try:
        client = await asyncio.to_thread(
            lambda: YouTubeAPIClient(client_secret_path=client_secret_path, token_path=token_path)
        )
    except Exception as exc:
        raise DiscoveryError("Failed to initialize YouTube API client") from exc

    # Get channel IDs
    channel_ids = await asyncio.to_thread(
        client.get_subscription_channel_ids,
        max_results=max_channels
    )
    print(f"[YouTube API] Found {len(channel_ids)} subscriptions")

    # Fetch videos from all channels in parallel
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _fetch_channel(idx: int, channel_id: str) -> List[VideoItem]:
        async with semaphore:
            return await discover_channel_async(channel_id, since_hours)

    tasks = [_fetch_channel(idx, channel_id) for idx, channel_id in enumerate(channel_ids)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and filter
    all_videos: List[VideoItem] = []
    failures: List[tuple[str, Exception]] = []
    for i, result in enumerate(results, 1):
        if isinstance(result, list):
            all_videos.extend(result)
            print(f"  → Channel {i}/{len(channel_ids)}: Found {len(result)} recent video(s)")
        elif isinstance(result, Exception):
            channel_id = channel_ids[i - 1]
            print(f"  → Channel {i}/{len(channel_ids)} ({channel_id}): Error: {result}")
            failures.append((channel_id, result))

    # Sort by published date (newest first)
    all_videos.sort(
        key=lambda v: v.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    print(f"[YouTube API] Total videos discovered: {len(all_videos)}")

    if failures:
        channel_id, error = failures[0]
        raise DiscoveryError(f"Failed to fetch channel {channel_id}") from error

    return all_videos


