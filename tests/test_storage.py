from __future__ import annotations

from tools.storage import has_changed, mark_processed, get_stored_hash


def test_has_changed_cycle(tmp_path, monkeypatch):
    # redirect DB to temp
    from tools import storage as st

    monkeypatch.setattr(st, "DB_PATH", tmp_path / "queue.sqlite", raising=False)

    url = "https://example.com/item"
    new_hash = "abc123"
    assert has_changed(url, new_hash) is True
    mark_processed(url, new_hash)
    assert get_stored_hash(url) == new_hash
    assert has_changed(url, new_hash) is False


