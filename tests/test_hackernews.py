"""Basic smoke test for HackerNews collector."""

from plugins.hackernews.collector import fetch_top_stories


def test_fetch_top_stories():
    """Verify HN collector returns a list (may be empty)."""
    # Use a very high score threshold to avoid fetching too many stories
    stories = fetch_top_stories(min_score=500, since_hours=24)
    
    # Should return a list (may be empty if no stories meet criteria)
    assert isinstance(stories, list)
    
    # If we got any stories, verify structure
    if stories:
        story = stories[0]
        assert hasattr(story, "id")
        assert hasattr(story, "title")
        assert hasattr(story, "url")
        assert hasattr(story, "score")
        assert hasattr(story, "time")
        assert hasattr(story, "by")
        assert hasattr(story, "hn_url")
        assert story.score >= 500
        assert story.hn_url.startswith("https://news.ycombinator.com/item?id=")

