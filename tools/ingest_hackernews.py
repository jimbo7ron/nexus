"""Ingest high-scoring Hacker News stories into Notion Articles database."""

from __future__ import annotations

from datetime import datetime, timezone

from notion_client import Client

from .config import load_feeds_config, load_summarize_config
from .notion import NotionWriter
from .utils import content_hash
from plugins.hackernews.collector import fetch_top_stories
from plugins.news.extractor import fetch_article_text
from .summarizer import Summarizer
from .storage import has_changed, mark_processed


def ingest_hackernews(
    client: Client,
    writer: NotionWriter,
    min_score: int = 100,
    since_hours: int = 24,
    console: bool = False,
) -> int:
    """
    Ingest HackerNews stories with high scores.
    
    Args:
        client: Notion client
        writer: NotionWriter instance
        min_score: Minimum HN score threshold
        since_hours: How many hours to look back
        console: Whether to print console output
    
    Returns:
        Number of stories processed
    """
    # Fetch high-scoring HN stories
    stories = fetch_top_stories(min_score=min_score, since_hours=since_hours)
    
    if not stories:
        if console:
            print(f"[HN] No stories found with score >= {min_score} in last {since_hours}h")
        return 0
    
    if console:
        print(f"[HN] Found {len(stories)} stories to process")
    
    summarizer = Summarizer(load_summarize_config())
    total = 0
    
    for story in stories:
        if console:
            print(f"\n[HN] Processing: {story.title} ({story.score} points)")
            print(f"     URL: {story.url}")
            print(f"     Discussion: {story.hn_url}")
        
        # Fetch article text from the actual URL
        text = fetch_article_text(story.url)
        if not text:
            writer.log_event(story.url, action="fetch", result="error", message="no content extracted")
            if console:
                print(f"     ❌ Could not extract article text")
            continue
        
        # Check for duplicates
        content_hash_val = content_hash(text)
        if not has_changed(story.url, content_hash_val):
            writer.log_event(story.url, action="fetch", result="skip", message="unchanged")
            if console:
                print(f"     ⏭️  Already processed (unchanged)")
            continue
        
        # Summarize the article
        try:
            summary_obj = summarizer.summarize_article(story.title, "Hacker News", text)
            
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
            
            writer.log_event(story.url, action="summarize", result="ok", message="LLM summary generated")
        except Exception as e:
            # Fallback: store truncated text with HN link
            summary_text = f"Hacker News Discussion: {story.hn_url}\nScore: {story.score} points\n\n{text[:1500]}"
            writer.log_event(story.url, action="summarize", result="error", message=str(e))
            if console:
                print(f"     ⚠️  Summarization failed, storing truncated text")
        
        if console:
            preview = (text[:300] or "").replace("\n", " ")
            print(f"     Content preview: {preview}...")
        
        # Store in Articles database
        now_iso = datetime.now(timezone.utc).isoformat()
        source = f"Hacker News ({story.score} points)"
        
        try:
            writer.upsert_article(
                title=story.title,
                url=story.url,
                summary=summary_text,
                body=text,
                source=source,
                published_iso=story.time.isoformat(),
                last_updated_iso=now_iso,
            )
            writer.log_event(story.url, action="write", result="ok", message="HN story upserted")
            mark_processed(story.url, content_hash_val)
            total += 1
            
            if console:
                print(f"     ✅ Successfully added to Notion")
        except Exception as e:
            writer.log_event(story.url, action="write", result="error", message=str(e))
            if console:
                print(f"     ❌ Error writing to Notion: {e}")
    
    return total

