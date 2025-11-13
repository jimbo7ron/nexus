from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from notion_client import Client

from .config import load_feeds_config, load_summarize_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.youtube.collector import (
    DiscoveryError,
    VideoItem,
    discover_channel_async,
    discover_feed_async,
    discover_subscriptions_via_api_async,
    shutdown_collector_executor,
)
from plugins.youtube.transcript import fetch_transcript_text_async
from .summarizer import Summarizer
from .storage import close_db, has_changed, mark_processed


class FatalIngestionError(Exception):
    """Raised when ingestion should abort entirely (e.g. transcript API blocked)."""


async def ingest_youtube(
    client: Client,
    writer: NotionWriter,
    since_hours: int = 24,
    console: bool = False,
    verbose: bool = False,
    workers: int = 10,
) -> int:
    """
    Ingest YouTube videos with async parallel processing.

    Args:
        client: Notion client
        writer: NotionWriter instance
        since_hours: How many hours to look back
        console: Whether to print console output (summary, one line per video)
        verbose: Whether to print verbose output (includes transcript preview)
        workers: Number of concurrent workers for processing videos

    Returns:
        Number of videos processed
    """
    # Fetch all videos
    try:
        videos = await _collect_all_videos(since_hours, console)
    except DiscoveryError as exc:
        if console:
            print(f"[YouTube] Discovery failed: {exc}")
        raise

    if not videos:
        if console:
            print(f"[YouTube] No videos found in last {since_hours}h")
        return 0

    if console:
        print(f"[YouTube] Found {len(videos)} videos to process with {workers} workers")

    summarizer = Summarizer(load_summarize_config())

    try:
        # Process videos in parallel with worker limit
        semaphore = asyncio.Semaphore(max(1, workers))

        async def process_video_with_limit(video: VideoItem):
            async with semaphore:
                return await _process_video(video, writer, summarizer, console, verbose)

        tasks = [process_video_with_limit(video) for video in videos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful processes and surface fatal errors
        total = 0
        first_fatal: FatalIngestionError | None = None
        for result in results:
            if isinstance(result, FatalIngestionError):
                first_fatal = first_fatal or result
            elif isinstance(result, Exception):
                if console:
                    print(f"[YouTube] Unexpected error: {result}")
            elif result:
                total += 1

        if first_fatal:
            raise first_fatal

        if console:
            print(f"\n[YouTube] Completed: {total}/{len(videos)} videos processed successfully")

        return total
    finally:
        # Cleanup: close all resources
        if console:
            print("[YouTube] Cleaning up resources...")

        # Close summarizer (OpenAI client)
        await summarizer.close()

        # Close database connection
        await close_db()

        # Give a moment for any pending operations to complete
        await asyncio.sleep(0.1)

        # Cancel any remaining tasks (except the current one)
        current_task = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t != current_task and not t.done()]
        if tasks and console:
            print(f"[YouTube] Cancelling {len(tasks)} remaining tasks...")
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await shutdown_collector_executor()

        # Shutdown default thread pool executor used by asyncio.to_thread()
        # Use the async shutdown method available in Python 3.9+
        try:
            loop = asyncio.get_running_loop()
            await loop.shutdown_default_executor()
        except Exception:
            pass  # Ignore errors during shutdown


async def _collect_all_videos(since_hours: int, console: bool) -> list[VideoItem]:
    """Collect videos from all configured sources."""
    feeds = load_feeds_config()
    use_api = feeds.get("youtube_use_api", False)
    subscription_feed = feeds.get("youtube_subscription_feed")
    channels = feeds.get("youtube_channels", []) or []
    max_channels = feeds.get("youtube_api_max_channels", 100)

    # Priority 1: Use YouTube Data API to fetch ALL subscriptions (RECOMMENDED)
    if use_api:
        if console:
            print(f"[YouTube] Using YouTube Data API to discover subscriptions...")
        return await discover_subscriptions_via_api_async(
            since_hours=since_hours,
            max_channels=max_channels,
        )

    # Priority 2: Use subscription RSS feed if available
    if subscription_feed:
        if console:
            print(f"[YouTube] Using subscription feed: {subscription_feed}")
        return await discover_feed_async(subscription_feed, since_hours=since_hours)

    # Priority 3: Fall back to individual channels
    if channels:
        if console:
            print(f"[YouTube] Monitoring {len(channels)} individual channel(s)")
        # Fetch all channels in parallel
        tasks = [discover_channel_async(channel_id, since_hours) for channel_id in channels]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results
        all_videos: list[VideoItem] = []
        for idx, result in enumerate(results):
            channel_id = channels[idx]
            if isinstance(result, list):
                all_videos.extend(result)
            elif isinstance(result, Exception):
                raise DiscoveryError(f"Failed to fetch channel {channel_id}") from result
        return all_videos

    if console:
        print("[YouTube] No YouTube sources configured. Set youtube_use_api=true or add channels.")
    return []


async def _process_video(video: VideoItem, writer: NotionWriter, summarizer: Summarizer, console: bool, verbose: bool) -> bool:
    """Process a single video. Returns True if successful, False otherwise."""
    try:
        # Console: one-line summary
        if console and not verbose:
            print(f"[YouTube] {video.title[:60]}... ", end=" ", flush=True)

        # Verbose: detailed output
        if verbose:
            print(f"\n[YouTube] Processing: {video.title}")
            print(f"     URL: {video.url}")
            print(f"     Channel: {video.channel or 'Unknown'}")

        # Fetch transcript
        try:
            transcript = await fetch_transcript_text_async(video.url)
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
                await writer.log_event(video.url, action="fetch", result="error", message=error_msg)
                if console and not verbose:
                    print(f"❌ API blocked")
                elif verbose:
                    print(f"     ❌ Transcript API blocked: {error_msg[:200]}")
                # Re-raise to stop entire ingestion
                raise FatalIngestionError(f"Transcript API blocked: {error_msg}") from e

            # Log other errors and continue
            await writer.log_event(video.url, action="fetch", result="error", message=error_msg)
            if console and not verbose:
                print(f"❌ Transcript error")
            elif verbose:
                print(f"     ❌ Transcript error: {e}")
            return False

        # Check for duplicates
        content_hash_val = content_hash(transcript)
        if not await has_changed(video.url, content_hash_val):
            await writer.log_event(video.url, action="fetch", result="skip", message="unchanged")
            if console and not verbose:
                print("⏭️  Skip (unchanged)")
            elif verbose:
                print(f"     ⏭️  Already processed (unchanged)")
            return False

        # Summarize
        try:
            if verbose:
                print(f"     🤖 Generating LLM summary...")
            summary_obj = await summarizer.summarize_video(video.title, video.channel, transcript)

            # Combine summary, takeaways, and key quotes into one Summary field
            summary_parts = [f"TL;DR: {summary_obj.tldr}", "", "Takeaways:"]
            summary_parts.extend([f"- {t}" for t in summary_obj.takeaways])
            if summary_obj.key_quotes:
                summary_parts.extend(["", "Key Quotes:"])
                summary_parts.extend([f"- {q}" for q in summary_obj.key_quotes])
            summary_text = "\n".join(summary_parts)

            await writer.log_event(video.url, action="summarize", result="ok", message="LLM summary generated")
            if verbose:
                print(f"     ✅ Summary generated ({len(summary_text)} chars)")
        except Exception as e:
            # Fallback: store truncated transcript
            summary_text = transcript[:2000]
            await writer.log_event(video.url, action="summarize", result="error", message=str(e))
            if console and not verbose:
                print(f"⚠️  Summary failed")
            elif verbose:
                print(f"     ⚠️  Summarization failed: {e}")

        if verbose:
            preview = (transcript[:300] or "").replace("\n", " ")
            print(f"     Transcript preview: {preview}...")

        # Construct thumbnail URL from video_id
        thumbnail = f"https://i.ytimg.com/vi/{video.video_id}/maxresdefault.jpg" if video.video_id else ""

        # Store in YouTube database
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            await writer.upsert_video(
                title=video.title,
                url=video.url,
                summary=summary_text,
                thumbnail=thumbnail,
                source=video.channel or "",
                published_iso=video.published.isoformat() if video.published else None,
                last_updated_iso=now_iso,
            )
            await writer.log_event(video.url, action="write", result="ok", message="video upserted")
            await mark_processed(video.url, content_hash_val)

            if console and not verbose:
                print("✅")
            elif verbose:
                print(f"     ✅ Successfully added to Notion")
            return True
        except Exception as e:
            await writer.log_event(video.url, action="write", result="error", message=str(e))
            if console and not verbose:
                print(f"❌ Write error")
            elif verbose:
                print(f"     ❌ Error writing to Notion: {e}")
            return False
    except FatalIngestionError:
        raise
    except Exception as e:
        if console:
            print(f"❌ Error: {e}")
        return False


async def ingest_youtube_url_async(
    writer: NotionWriter | None,
    url: str,
    console: bool = False,
    dry_run: bool = False,
) -> int:
    """Async helper to ingest a single YouTube video by URL."""
    from plugins.youtube.metadata import extract_metadata_async

    metadata = await extract_metadata_async(url)
    title = metadata["title"]
    channel = metadata["channel"]
    published_iso = metadata["published_iso"]
    thumbnail = metadata.get("thumbnail", "")

    if "error" in metadata and writer:
        await writer.log_event(url, action="fetch", result="error", message=f"Metadata error: {metadata['error']}")

    try:
        transcript = await fetch_transcript_text_async(url)
    except Exception as e:
        error_msg = str(e)
        exception_type = type(e).__name__

        is_blocked = (
            exception_type == "IpBlocked"
            or "429" in error_msg
            or "rate limit" in error_msg.lower()
            or "blocking" in error_msg.lower()
        )

        if is_blocked:
            print(f"[YouTube] Transcript API blocked. Stopping. Error: {error_msg[:200]}")
            if writer:
                await writer.log_event(url, action="fetch", result="error", message=error_msg)
            raise FatalIngestionError(f"Transcript API blocked: {error_msg}") from e

        if writer:
            await writer.log_event(url, action="fetch", result="error", message=error_msg)
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

    if not await has_changed(url, content_hash_val):
        await writer.log_event(url, action="fetch", result="skip", message="unchanged")
        return 0

    summarizer = Summarizer(load_summarize_config())
    try:
        try:
            summary_obj = await summarizer.summarize_video(title, channel, transcript)
            summary_parts = [f"TL;DR: {summary_obj.tldr}", "", "Takeaways:"]
            summary_parts.extend([f"- {t}" for t in summary_obj.takeaways])
            if summary_obj.key_quotes:
                summary_parts.extend(["", "Key Quotes:"])
                summary_parts.extend([f"- {q}" for q in summary_obj.key_quotes])
            summary_text = "\n".join(summary_parts)
            await writer.log_event(url, action="summarize", result="ok", message="LLM summary generated")
        except Exception as e:
            summary_text = f"[Summarization failed: {str(e)}]\n\n{transcript[:2000]}"
            await writer.log_event(url, action="summarize", result="error", message=str(e))

        now_iso = datetime.now(timezone.utc).isoformat()
        await writer.upsert_video(
            title=title,
            url=url,
            summary=summary_text,
            thumbnail=thumbnail,
            source=channel,
            published_iso=published_iso,
            last_updated_iso=now_iso,
        )
        await writer.log_event(url, action="write", result="ok", message="video upserted")
        await mark_processed(url, content_hash_val)
        return 1
    finally:
        await summarizer.close()
        await close_db()


def ingest_youtube_url(
    writer: NotionWriter | None,
    url: str,
    console: bool = False,
    dry_run: bool = False,
) -> int:
    """Synchronous wrapper for async URL ingestion (for CLI compatibility)."""
    return asyncio.run(ingest_youtube_url_async(writer, url, console=console, dry_run=dry_run))


