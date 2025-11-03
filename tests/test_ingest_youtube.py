from __future__ import annotations

from datetime import datetime, timezone

import types


def test_ingest_youtube_happy_path(monkeypatch, tmp_path):
    # Redirect storage DB to temp
    import tools.storage as storage

    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "queue.sqlite", raising=False)

    # Mock feeds config
    import tools.ingest_youtube as iy

    monkeypatch.setattr(iy, "load_feeds_config", lambda: {"youtube_channels": ["UC_TEST"]})

    # Build a fake video item
    from plugins.youtube.collector import VideoItem

    fake_item = VideoItem(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Test Video",
        published=datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc),
        channel="Test Channel",
        video_id="dQw4w9WgXcQ",
    )

    monkeypatch.setattr(iy, "discover_channel", lambda channel_id, since_hours=24: [fake_item])
    monkeypatch.setattr(iy, "fetch_transcript_text", lambda url: "hello transcript")

    # Fake Notion writer capturing calls
    class FakeWriter:
        def __init__(self):
            self.client = None
            self.upserts = []
            self.logs = []

        def upsert_video(self, **kwargs):
            self.upserts.append(kwargs)
            return "page-id"

        def log_event(self, item_url: str, action: str, result: str, message: str = ""):
            self.logs.append((item_url, action, result, message))
            return "log-id"

    writer = FakeWriter()

    # First run should ingest 1
    count1 = iy.ingest_youtube_since(client=None, writer=writer, since_hours=24)
    assert count1 == 1
    assert writer.upserts and writer.upserts[0]["url"] == fake_item.url
    assert any(l[2] == "ok" for l in writer.logs)

    # Second run should detect unchanged (dedupe) and skip
    writer2 = FakeWriter()
    count2 = iy.ingest_youtube_since(client=None, writer=writer2, since_hours=24)
    assert count2 == 0
    # Expect a skip log due to unchanged content
    assert any(l[2] == "skip" for l in writer2.logs)


