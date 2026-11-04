"""Offline contract tests for the news.v1 lake/API boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from news_data import config
from news_data import api, store


LAKE_HELPERS = store.product_store_available()
NEEDS_LAKE = unittest.skipUnless(
    LAKE_HELPERS,
    "data_lake helpers not found; install solo-empire-data-lake or set SOLO_DATA_LAKE_ROOT",
)


class NewsDataApiTests(unittest.TestCase):
    @NEEDS_LAKE
    def test_news_item_preserves_attribution_and_normalizes_headline(self) -> None:
        item = store.news_item_from_bronze(
            {
                "event_time": "2026-09-08T00:00:00Z",
                "source_record_id": "Demo Publisher|article-001",
                "ingest_run_id": "run-001",
                "raw_object_key": "landing/source=book-news-scraping/batch-001/payload.csv",
                "payload_json": json.dumps(
                    {
                        "id": "Demo Publisher|article-001",
                        "source": "Demo Publisher",
                        "article_id": "article-001",
                        "title": "Example headline",
                        "url": "https://publisher.example/news/article-001",
                        "source_url": "https://publisher.example/feed",
                        "captured_at": "2026-09-08T00:00:00Z",
                        "capture_kind": "rss_article",
                    }
                ),
            }
        )
        self.assertEqual(item["headline"], "Example headline")
        self.assertEqual(item["canonical_url"], "https://publisher.example/news/article-001")
        self.assertEqual(item["publisher"], "Demo Publisher")
        self.assertEqual(item["capture_kind"], "rss_article")
        self.assertTrue(item["record_id"])

    def test_news_api_is_get_only_by_default(self) -> None:
        text = Path(api.__file__).read_text(encoding="utf-8")
        self.assertEqual(config.SCHEMA_VERSION, "news.v1")
        self.assertEqual(config.API_PORT, 8108)
        for path in ("/healthz", "/v1/metadata", "/v1/records", "/v1/history", "/v1/refresh"):
            self.assertIn(path, text)
        self.assertIn('data_status="forbidden"', text)
        self.assertFalse(config.ALLOW_REFRESH)

    @NEEDS_LAKE
    def test_history_deduplicates_replays_but_keeps_new_observation_times(self) -> None:
        base = {
            "source": "Matichon",
            "article_id": "article-001",
            "source_record_id": "Matichon|article-001",
            "canonical_url": "https://publisher.example/news/article-001",
            "headline": "Example headline",
            "event_time": "2026-09-08T00:00:00Z",
            "updated_at": "2026-09-08T00:00:00Z",
            "ingest_run_id": "run-001",
            "raw_object_key": "landing/batch-001/payload.csv",
        }
        duplicate = {**base, "ingest_run_id": "run-002", "raw_object_key": "landing/batch-002/payload.csv"}
        later = {**base, "event_time": "2026-09-08T01:00:00Z", "updated_at": "2026-09-08T01:00:00Z"}
        items = store.deduplicate_history_items([base, duplicate, later])
        self.assertEqual(len(items), 2)
        self.assertEqual([item["record_id"] for item in items], ["Matichon|article-001#h0", "Matichon|article-001#h1"])

class LakeWindowTests(unittest.TestCase):
    def _calls(self, **kwargs: object) -> list[dict[str, object]]:
        calls: list[dict[str, object]] = []

        class FakeProductStore:
            def load_bronze_dataset(self, *_args: object, **options: object) -> dict[str, object]:
                calls.append(options)
                return {"items": []}

        with patch.object(store, "_ps_mod", return_value=FakeProductStore()), patch.object(
            store, "_contract", return_value=object()
        ):
            store.load_records(data_lake_uri="s3://lake", **kwargs)  # type: ignore[arg-type]
            store.load_history(data_lake_uri="s3://lake", **kwargs)  # type: ignore[arg-type]
        return calls

    def test_min_ingest_date_reaches_both_bronze_reads(self) -> None:
        calls = self._calls(min_ingest_date="2026-11-03")
        self.assertEqual([c["min_ingest_date"] for c in calls], ["2026-11-03", "2026-11-03"])

    def test_unbounded_reads_omit_the_option_for_older_lake_pins(self) -> None:
        self.assertTrue(all("min_ingest_date" not in c for c in self._calls()))

