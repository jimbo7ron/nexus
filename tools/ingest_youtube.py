from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from notion_client import Client

from .config import load_feeds_config, load_summarize_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.youtube.collector import discover_channel, discover_feed, discover_subscriptions_via_api, VideoItem
from plugins.youtube.transcript import fetch_transcript_text
from .summarizer import Summarizer
from .storage import has_changed, mark_processed


def _process_video_items(
    items: list[VideoItem],
    writer: NotionWriter,
    summarizer: Summarizer,
    console: bool = False,
) -> int:
    """Process a list of video items: fetch transcript, summarize, and upsert to Notion."""
    total = 0
    for item in items:
        try:
            transcript = fetch_transcript_text(item.url)
        except Exception as e:
            error_msg = str(e)
            exception_type = type(e).__name__
            
            # Stop processing if transcript API is blocked
            is_blocked = (
                exception_type == "IpBlocked" or
                "429" in error_msg or 
                "rate limit" in error_msg.lower() or
                "blocking" in error_msg.lower()
            )
            
            if is_blocked:
                print(f"[YouTube] Transcript API blocked. Stopping ingestion. Error: {error_msg[:200]}")
                writer.log_event(item.url, action="fetch", result="error", message=error_msg)
                raise
            
            # Log other errors and continue
            writer.log_event(item.url, action="fetch", result="error", message=error_msg)
            continue
        
        content_hash_val = content_hash(transcript)
        now_iso = datetime.now(timezone.utc).isoformat()
        if not has_changed(item.url, content_hash_val):
            writer.log_event(item.url, action="fetch", result="skip", message="unchanged")
            continue
        
        # Summarize
        try:
            summary_obj = summarizer.summarize_video(item.title, item.channel, transcript)
            # Combine summary, takeaways, and key quotes into one Summary field
            summary_parts = [f"TL;DR: {summary_obj.tldr}", "", "Takeaways:"]
            summary_parts.extend([f"- {t}" for t in summary_obj.takeaways])
            if summary_obj.key_quotes:
                summary_parts.extend(["", "Key Quotes:"])
                summary_parts.extend([f"- {q}" for q in summary_obj.key_quotes])
            summary_text = "\n".join(summary_parts)
        except Exception as e:
            # Fallback: store truncated transcript as summary
            summary_text = transcript[:2000]
            writer.log_event(item.url, action="summarize", result="error", message=str(e))
        
        if console:
            preview = transcript[:500].replace("\n", " ")
            print(f"[YouTube] {item.title} | {item.url}\nChannel: {item.channel or ''}\nPublished: {item.published or ''}\nTranscript preview: {preview}...")
        
        # Construct thumbnail URL from video_id
        thumbnail = f"https://i.ytimg.com/vi/{item.video_id}/maxresdefault.jpg" if item.video_id else ""
        
        writer.upsert_video(
            title=item.title,
            url=item.url,
            summary=summary_text,
            thumbnail=thumbnail,
            source=item.channel or "",
            published_iso=item.published.isoformat() if item.published else None,
            last_updated_iso=now_iso,
        )
        writer.log_event(item.url, action="write", result="ok", message="video upserted")
        mark_processed(item.url, content_hash_val)
        total += 1
    return total


def ingest_youtube_since(
    client: Client,
    writer: NotionWriter,
    since_hours: int = 24,
    console: bool = False,
) -> int:
    feeds = load_feeds_config()
    use_api = feeds.get("youtube_use_api", False)
    subscription_feed = feeds.get("youtube_subscription_feed")
    channels = feeds.get("youtube_channels", []) or []
    max_channels = feeds.get("youtube_api_max_channels", 100)
    summarizer = Summarizer(load_summarize_config())
    total = 0
    
    # Priority 1: Use YouTube Data API to fetch ALL subscriptions (RECOMMENDED)
    if use_api:
        print(f"[YouTube] Using YouTube Data API to discover subscriptions...")
        items = discover_subscriptions_via_api(
            since_hours=since_hours,
            max_channels=max_channels,
        )
        total += _process_video_items(items, writer, summarizer, console)
        return total
    
    # Priority 2: Use subscription RSS feed if available
    if subscription_feed:
        print(f"[YouTube] Using subscription feed: {subscription_feed}")
        items = discover_feed(subscription_feed, since_hours=since_hours)
        total += _process_video_items(items, writer, summarizer, console)
    
    # Priority 3: Fall back to individual channels
    if channels:
        print(f"[YouTube] Monitoring {len(channels)} individual channel(s)")
        for channel_id in channels:
            items = discover_channel(channel_id, since_hours=since_hours)
            total += _process_video_items(items, writer, summarizer, console)
    
    if not subscription_feed and not channels and not use_api:
        print("[YouTube] No YouTube sources configured. Set youtube_use_api=true or add channels.")
    
    return total


def ingest_youtube_url(
    writer: NotionWriter | None,
    url: str,
    console: bool = False,
    dry_run: bool = False,
) -> int:
    # Extract video metadata
    from plugins.youtube.metadata import extract_metadata
    
    metadata = extract_metadata(url)
    title = metadata['title']
    channel = metadata['channel']
    published_iso = metadata['published_iso']
    thumbnail = metadata.get('thumbnail', '')
    
    if 'error' in metadata and writer:
        writer.log_event(url, action="fetch", result="error", message=f"Metadata error: {metadata['error']}")
    
    # Fetch transcript
    try:
        transcript = fetch_transcript_text(url)
    except Exception as e:
        error_msg = str(e)
        exception_type = type(e).__name__
        
        # Stop if transcript API is blocked (check both exception type and message)
        is_blocked = (
            exception_type == "IpBlocked" or
            "429" in error_msg or 
            "rate limit" in error_msg.lower() or
            "blocking" in error_msg.lower()
        )
        
        if is_blocked:
            print(f"[YouTube] Transcript API blocked. Stopping. Error: {error_msg[:200]}")
            if writer:
                writer.log_event(url, action="fetch", result="error", message=error_msg)
            raise
        
        # Log other errors but don't stop
        if writer:
            writer.log_event(url, action="fetch", result="error", message=error_msg)
        print(f"[YouTube] fetch error: {e}")
        return 0

    content_hash_val = content_hash(transcript)
    if console:
        preview = transcript[:1000].replace("\n", " ")
        print(f"[YouTube] {url}")
        print(f"Title: {title}")
        print(f"Channel: {channel}")
        print(f"Transcript preview: {preview}...")

    if dry_run:
        return 1

    if writer is None:
        print("[YouTube] writer missing and not in dry-run; skipping upsert")
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    if not has_changed(url, content_hash_val):
        writer.log_event(url, action="fetch", result="skip", message="unchanged")
        return 0

    # Summarize with LLM
    summarizer = Summarizer(load_summarize_config())
    try:
        summary_obj = summarizer.summarize_video(title, channel, transcript)
        # Combine summary, takeaways, and key quotes into one Summary field
        summary_parts = [f"TL;DR: {summary_obj.tldr}", "", "Takeaways:"]
        summary_parts.extend([f"- {t}" for t in summary_obj.takeaways])
        if summary_obj.key_quotes:
            summary_parts.extend(["", "Key Quotes:"])
            summary_parts.extend([f"- {q}" for q in summary_obj.key_quotes])
        summary_text = "\n".join(summary_parts)
        writer.log_event(url, action="summarize", result="ok", message="LLM summary generated")
    except Exception as e:
        # Fallback: store truncated transcript
        summary_text = f"[Summarization failed: {str(e)}]\n\n{transcript[:2000]}"
        if writer:
            writer.log_event(url, action="summarize", result="error", message=str(e))

    # Upsert to Notion with full metadata
    writer.upsert_video(
        title=title,
        url=url,
        summary=summary_text,
        thumbnail=thumbnail,
        source=channel,
        published_iso=published_iso,
        last_updated_iso=now_iso,
    )
    writer.log_event(url, action="write", result="ok", message="video upserted")
    mark_processed(url, content_hash_val)
    return 1


