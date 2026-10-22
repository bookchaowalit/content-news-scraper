"""Capture files must be replaced atomically.

The parent control plane replays ``data/exported/<feed>.csv`` and the raw XML
into Bronze. ``write_snapshot`` opened the target with ``"w"`` (truncating it)
and then wrote row by row, so a run killed or failing mid-write left a
truncated or empty snapshot where the last good capture used to be.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news import feed_common

FIELDS = ["captured_at", "article_id", "title"]


def _rows_then_crash():
    yield {"article_id": "a1", "title": "First"}
    raise OSError("disk full")


def test_failed_snapshot_write_keeps_the_previous_file(tmp_path):
    target = tmp_path / "matichon_news.csv"
    feed_common.write_snapshot(target, FIELDS, [{"article_id": "old", "title": "Old"}], "2026-10-21T00:00:00Z")
    before = target.read_text(encoding="utf-8")
    with pytest.raises(OSError):
        feed_common.write_snapshot(target, FIELDS, _rows_then_crash(), "2026-10-22T00:00:00Z")
    assert target.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["matichon_news.csv"]


def test_failed_raw_write_keeps_the_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "matichon_news_raw.xml"
    feed_common.write_bytes(b"<rss>old</rss>", target)

    def broken_fsync(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(feed_common.os, "fsync", broken_fsync)
    with pytest.raises(OSError):
        feed_common.write_bytes(b"<rss>new</rss>", target)
    assert target.read_bytes() == b"<rss>old</rss>"
    assert [p.name for p in tmp_path.iterdir()] == ["matichon_news_raw.xml"]


def test_successful_writes_replace_the_file(tmp_path):
    target = tmp_path / "out.csv"
    feed_common.write_snapshot(target, FIELDS, [{"article_id": "a", "title": "A"}], "t1")
    feed_common.write_snapshot(target, FIELDS, [{"article_id": "b", "title": "B"}], "t2")
    assert target.read_text(encoding="utf-8").splitlines() == ["captured_at,article_id,title", "t2,b,B"]
    raw = tmp_path / "raw.xml"
    feed_common.write_bytes(b"one", raw)
    feed_common.write_bytes(b"two", raw)
    assert raw.read_bytes() == b"two"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.csv", "raw.xml"]
