from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_ingest_youtube_happy_path(monkeypatch, tmp_path):
    import tools.storage as storage
    import tools.ingest_youtube as iy
    from plugins.youtube.collector import VideoItem

    # Redirect storage DB to temp
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "queue.sqlite", raising=False)

    # Mock feeds config
    monkeypatch.setattr(iy, "load_feeds_config", lambda: {"youtube_channels": ["UC_TEST"]})

    fake_item = VideoItem(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Test Video",
        published=datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc),
        channel="Test Channel",
        video_id="dQw4w9WgXcQ",
    )

    async def fake_discover_channel(channel_id: str, since_hours: int = 24):
        assert channel_id == "UC_TEST"
        return [fake_item]

    monkeypatch.setattr(iy, "discover_channel_async", fake_discover_channel)
    async def fake_fetch_transcript_text_async(url: str):
        assert url == fake_item.url
        return "hello transcript"

    monkeypatch.setattr(iy, "fetch_transcript_text_async", fake_fetch_transcript_text_async)

    class FakeSummary:
        tldr = "Short summary"
        takeaways = ["Takeaway 1"]
        key_quotes = ["Quote 1"]

    class FakeSummarizer:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def summarize_video(self, *args, **kwargs):
            return FakeSummary()

        async def close(self):
            self.closed = True

    monkeypatch.setattr(iy, "Summarizer", FakeSummarizer)

    class FakeWriter:
        def __init__(self):
            self.client = None
            self.upserts = []
            self.logs = []

        async def upsert_video(self, **kwargs):
            self.upserts.append(kwargs)
            return "page-id"

        async def log_event(self, item_url: str, action: str, result: str, message: str = ""):
            self.logs.append((item_url, action, result, message))
            return "log-id"

    writer = FakeWriter()

    count1 = await iy.ingest_youtube(writer=writer, since_hours=24)
    assert count1 == 1
    assert writer.upserts and writer.upserts[0]["url"] == fake_item.url
    assert any(result == "ok" for (_, _, result, _) in writer.logs)

    writer2 = FakeWriter()
    count2 = await iy.ingest_youtube(writer=writer2, since_hours=24)
    assert count2 == 0
    assert any(result == "skip" for (_, _, result, _) in writer2.logs)


@pytest.mark.asyncio
async def test_ingest_youtube_transcript_block(monkeypatch, tmp_path):
    import tools.storage as storage
    import tools.ingest_youtube as iy
    from plugins.youtube.collector import VideoItem

    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "queue.sqlite", raising=False)
    monkeypatch.setattr(iy, "load_feeds_config", lambda: {"youtube_channels": ["UC_TEST"]})

    fake_item = VideoItem(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Blocked Video",
        published=datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc),
        channel="Test Channel",
        video_id="dQw4w9WgXcQ",
    )

    async def fake_discover_channel(_channel_id: str, since_hours: int = 24):
        return [fake_item]

    async def blocked_transcript(_url: str):
        raise RuntimeError("429 Too Many Requests")

    class FakeSummarizer:
        def __init__(self, *args, **kwargs):
            pass

        async def summarize_video(self, *args, **kwargs):
            return None

        async def close(self):
            pass

    class FakeWriter:
        client = None

        async def upsert_video(self, **kwargs):
            return "page-id"

        async def log_event(self, item_url: str, action: str, result: str, message: str = ""):
            return "log-id"

    monkeypatch.setattr(iy, "discover_channel_async", fake_discover_channel)
    monkeypatch.setattr(iy, "fetch_transcript_text_async", blocked_transcript)
    monkeypatch.setattr(iy, "Summarizer", FakeSummarizer)

    with pytest.raises(iy.FatalIngestionError):
        await iy.ingest_youtube(writer=FakeWriter(), since_hours=24, console=False)
