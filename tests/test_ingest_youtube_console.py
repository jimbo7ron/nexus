from __future__ import annotations

from datetime import datetime, timezone


def test_ingest_youtube_console(monkeypatch, tmp_path, capsys):
    # Redirect storage DB to temp
    import tools.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "queue.sqlite", raising=False)

    # Mock feeds config
    import tools.ingest_youtube as iy
    monkeypatch.setattr(iy, "load_feeds_config", lambda: {"youtube_channels": ["UC_TEST"]})

    # Fake video item
    from plugins.youtube.collector import VideoItem
    fake_item = VideoItem(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Test Video",
        published=datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc),
        channel="Test Channel",
        video_id="dQw4w9WgXcQ",
    )

    monkeypatch.setattr(iy, "discover_channel", lambda channel_id, since_hours=24: [fake_item])
    monkeypatch.setattr(iy, "fetch_transcript_text", lambda url: "hello transcript " * 50)

    # Fake Notion writer (no-op)
    class FakeWriter:
        def __init__(self):
            self.client = None
        def upsert_video(self, **kwargs):
            return "page-id"
        def log_event(self, item_url: str, action: str, result: str, message: str = ""):
            return "log-id"

    writer = FakeWriter()

    # Call with console=True to print preview
    count = iy.ingest_youtube_since(client=None, writer=writer, since_hours=24, console=True)
    assert count == 1

    # Ensure something was printed (preview line)
    out = capsys.readouterr().out
    assert "[YouTube] Test Video" in out
    assert "Transcript preview:" in out


