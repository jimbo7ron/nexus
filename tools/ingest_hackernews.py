"""Ingest high-scoring Hacker News stories into Notion Articles database."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from notion_client import Client

from .config import load_feeds_config, load_summarize_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.hackernews.collector import fetch_top_stories
from plugins.news.extractor import fetch_article_text
from .summarizer import Summarizer
from .storage import has_changed, mark_processed, close_db


async def ingest_hackernews(
    client: Client,
    writer: NotionWriter,
    min_score: int = 100,
    since_hours: int = 24,
    console: bool = False,
    verbose: bool = False,
    workers: int = 10,
) -> int:
    """
    Ingest HackerNews stories with high scores.

    Args:
        client: Notion client
        writer: NotionWriter instance
        min_score: Minimum HN score threshold
        since_hours: How many hours to look back
        console: Whether to print console output (summary, one line per story)
        verbose: Whether to print verbose output (includes content preview, summary details)
        workers: Number of concurrent workers for processing stories

    Returns:
        Number of stories processed
    """
    # Fetch high-scoring HN stories
    stories = await fetch_top_stories(min_score=min_score, since_hours=since_hours)

    if not stories:
        if console:
            print(f"[HN] No stories found with score >= {min_score} in last {since_hours}h")
        return 0

    if console:
        print(f"[HN] Found {len(stories)} stories to process with {workers} workers")

    summarizer = Summarizer(load_summarize_config())

    try:
        # Process stories in parallel with worker limit
        semaphore = asyncio.Semaphore(workers)

        async def process_story_with_limit(story):
            async with semaphore:
                return await _process_story(story, writer, summarizer, console, verbose)

        results = await asyncio.gather(
            *[process_story_with_limit(story) for story in stories],
            return_exceptions=True
        )

        # Count successful processes
        total = sum(1 for r in results if r is True)

        if console:
            print(f"\n[HN] Completed: {total}/{len(stories)} stories processed successfully")

        return total
    finally:
        # Cleanup: close all resources
        if console:
            print("[HN] Cleaning up resources...")

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
            print(f"[HN] Cancelling {len(tasks)} remaining tasks...")
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def _process_story(story, writer: NotionWriter, summarizer: Summarizer, console: bool, verbose: bool) -> bool:
    """Process a single story. Returns True if successful, False otherwise."""
    try:
        # Console: one-line summary
        if console and not verbose:
            print(f"[HN] {story.title[:60]}... ({story.score} pts)", end=" ", flush=True)

        # Verbose: detailed output
        if verbose:
            print(f"\n[HN] Processing: {story.title} ({story.score} points)")
            print(f"     URL: {story.url}")
            print(f"     Discussion: {story.hn_url}")

        # Fetch article text from the actual URL
        text = await fetch_article_text(story.url)
        if not text:
            await writer.log_event(story.url, action="fetch", result="error", message="no content extracted")
            if console and not verbose:
                print("❌ No content")
            elif verbose:
                print(f"     ❌ Could not extract article text")
            return False

        # Check for duplicates
        content_hash_val = content_hash(text)
        if not await has_changed(story.url, content_hash_val):
            await writer.log_event(story.url, action="fetch", result="skip", message="unchanged")
            if console and not verbose:
                print("⏭️  Skip (unchanged)")
            elif verbose:
                print(f"     ⏭️  Already processed (unchanged)")
            return False

        # Summarize the article
        try:
            if verbose:
                print(f"     🤖 Generating LLM summary...")
            summary_obj = await summarizer.summarize_article(story.title, "Hacker News", text)

            # Build summary with HN discussion link at the top
            summary_parts = [
                f"Hacker News Discussion: {story.hn_url}",
                f"Score: {story.score} points by {story.by}",
                "",
                f"TL;DR: {summary_obj.tldr}",
                "",
                "Takeaways:"
            ]
            summary_parts.extend([f"- {t}" for t in summary_obj.takeaways])

            if summary_obj.key_quotes:
                summary_parts.extend(["", "Key Quotes:"])
                summary_parts.extend([f"- {q}" for q in summary_obj.key_quotes])

            summary_text = "\n".join(summary_parts)

            await writer.log_event(story.url, action="summarize", result="ok", message="LLM summary generated")
            if verbose:
                print(f"     ✅ Summary generated ({len(summary_text)} chars)")
        except Exception as e:
            # Fallback: store truncated text with HN link
            summary_text = f"Hacker News Discussion: {story.hn_url}\nScore: {story.score} points\n\n{text[:1500]}"
            await writer.log_event(story.url, action="summarize", result="error", message=str(e))
            if console and not verbose:
                print(f"⚠️  Summary failed")
            elif verbose:
                print(f"     ⚠️  Summarization failed: {e}")

        if verbose:
            preview = (text[:300] or "").replace("\n", " ")
            print(f"     Content preview: {preview}...")

        # Store in Articles database
        now_iso = datetime.now(timezone.utc).isoformat()
        source = f"Hacker News ({story.score} points)"

        try:
            await writer.upsert_article(
                title=story.title,
                url=story.url,
                summary=summary_text,
                body=text,
                source=source,
                published_iso=story.time.isoformat(),
                last_updated_iso=now_iso,
            )
            await writer.log_event(story.url, action="write", result="ok", message="HN story upserted")
            await mark_processed(story.url, content_hash_val)

            if console and not verbose:
                print("✅")
            elif verbose:
                print(f"     ✅ Successfully added to Notion")
            return True
        except Exception as e:
            await writer.log_event(story.url, action="write", result="error", message=str(e))
            if console and not verbose:
                print(f"❌ Write error")
            elif verbose:
                print(f"     ❌ Error writing to Notion: {e}")
            return False
    except Exception as e:
        if console:
            print(f"❌ Error: {e}")
        return False
