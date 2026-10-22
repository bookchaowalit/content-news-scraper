"""Offline check of the capture rows and API items against news-data-contract-v1.

The contract lives in the private architecture-docs repository
(``systems/architecture/news-data-contract-v1.yaml``), which CI cannot read, so
the field list below is a copy taken on 2026-10-22. Fields the contract lists
but the code does not produce are pinned in ``KNOWN_GAPS``: fixing a gap (or the
contract changing) makes this test fail until the copy is updated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from news import feed_adapter
from news_data import config, store
from run_feeds import FEEDS

RECORD_FIELDS = {
    "article_id",
    "title",
    "headline",
    "url",
    "canonical_url",
    "summary",
    "author",
    "categories",
    "section",
    "topics",
    "published_at",
    "updated_at",
    "image_url",
    "publisher",
    "source",
    "source_url",
    "source_feed_url",
    "observed_at",
    "capture_kind",
}
PER_FEED_EXTRAS = {"categories", "section", "topics"}
# Capture-only columns: captured_at becomes the Bronze event_time; feed_title is
# provenance the contract does not list.
CAPTURE_ONLY = {"captured_at", "feed_title"}
# Listed by the contract, produced by neither the capture nor the API item.
KNOWN_GAPS = {"source_feed_url"}

FIXTURES = {
    "matichon_news": "matichon_feed.xml",
    "thai_business_news": "bangkok_post_business.xml",
    "thai_tech_news": "blognone_atom.xml",
    "notebookspec_tech": "notebookspec_feed.xml",
}


def _specs() -> list[feed_adapter.FeedSpec]:
    return [cls.spec for _name, cls in FEEDS]


def test_contract_identity_matches_config():
    assert config.SCHEMA_VERSION == "news.v1"
    assert config.API_PORT == 8108
    assert config.ID_FIELDS == ["source", "article_id"]
    assert config.ID_SEP == "|"
    assert (config.LAKE_DATASET_ARTICLES, config.LAKE_DATASET_HISTORY) == ("articles", "articles_history")


def test_capture_columns_are_contract_fields():
    for spec in _specs():
        extra = set(spec.snapshot_fields) - RECORD_FIELDS - CAPTURE_ONLY
        assert extra == set(), spec.key


def test_contracted_feeds_cover_every_per_feed_extra():
    produced = set().union(*(spec.snapshot_fields for spec in _specs()))
    assert PER_FEED_EXTRAS <= produced


def _api_item(spec: feed_adapter.FeedSpec, row: dict) -> dict:
    payload = {**row, "captured_at": "2026-10-22T00:00:00Z", "id": f"{row['source']}|{row['article_id']}"}
    return store.news_item_from_bronze(
        {
            "event_time": "2026-10-22T00:00:00Z",
            "source_record_id": payload["id"],
            "ingest_run_id": "run-1",
            "raw_object_key": f"landing/{spec.key}.csv",
            "payload_json": json.dumps(payload),
        }
    )


def test_api_items_from_fixture_captures_carry_the_contract_fields():
    for spec in _specs():
        raw = (ROOT / "tests" / "fixtures" / FIXTURES[spec.key]).read_bytes()
        _, rows = feed_adapter.parse_feed(spec, raw)
        assert rows, spec.key
        for row in rows:
            item = _api_item(spec, row)
            expected = RECORD_FIELDS - PER_FEED_EXTRAS - KNOWN_GAPS
            assert expected <= set(item), (spec.key, expected - set(item))
            assert KNOWN_GAPS.isdisjoint(item), "gap fixed: update KNOWN_GAPS and the contract findings"
            # identity = source|article_id; the lake runtime hashes long/unsafe ids
            # into the URL-safe record_id, so compare through the same helper.
            assert item["source_record_id"] == f"{row['source']}|{row['article_id']}"
            assert item["record_id"] == store.make_record_id({"source": row["source"], "article_id": row["article_id"]})
            assert item["publisher"] == spec.source_name
            assert item["canonical_url"].startswith("https://")
