from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_ingest_youtube_console(monkeypatch, tmp_path, capsys):
    import tools.storage as storage
    import tools.ingest_youtube as iy
    from plugins.youtube.collector import VideoItem

    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "queue.sqlite", raising=False)
    monkeypatch.setattr(iy, "load_feeds_config", lambda: {"youtube_channels": ["UC_TEST"]})

    fake_item = VideoItem(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Test Video",
        published=datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc),
        channel="Test Channel",
        video_id="dQw4w9WgXcQ",
    )

    async def fake_discover_channel(channel_id: str, since_hours: int = 24):
        return [fake_item]

    async def fake_fetch_transcript(url: str):
        return "hello transcript " * 50

    class FakeSummary:
        tldr = "Summary"
        takeaways = ["Takeaway"]
        key_quotes = []

    class FakeSummarizer:
        def __init__(self, *args, **kwargs):
            pass

        async def summarize_video(self, *args, **kwargs):
            return FakeSummary()

        async def close(self):
            pass

    class FakeWriter:
        def __init__(self):
            self.client = None

        async def upsert_video(self, **kwargs):
            return "page-id"

        async def log_event(self, item_url: str, action: str, result: str, message: str = ""):
            return "log-id"

    monkeypatch.setattr(iy, "discover_channel_async", fake_discover_channel)
    monkeypatch.setattr(iy, "fetch_transcript_text_async", fake_fetch_transcript)
    monkeypatch.setattr(iy, "Summarizer", FakeSummarizer)

    count = await iy.ingest_youtube(writer=FakeWriter(), since_hours=24, console=True)
    assert count == 1

    out = capsys.readouterr().out
    assert "[YouTube] Test Video" in out
    assert "✅" in out


