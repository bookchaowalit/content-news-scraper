"""Bronze-backed store for the news.v1 read-only API."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Optional

from . import config


def product_store_available() -> bool:
    """Return True when the shared ``data_lake`` helpers can be imported."""

    try:
        _ps_mod()
    except ImportError:
        return False
    return True


def _load_product_store():
    root = config.SOLO_DATA_LAKE_ROOT.strip()
    if root and importlib.util.find_spec("data_lake") is None:
        scripts = Path(root).expanduser().resolve() / "infra" / "scripts"
        if (scripts / "data_lake" / "product_store.py").is_file() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
    from data_lake import product_store as ps  # type: ignore

    return ps


_ps = None


def _ps_mod():
    global _ps
    if _ps is None:
        _ps = _load_product_store()
    return _ps


def _lake_uri() -> Optional[str]:
    return config.DATA_LAKE_URI.strip() or None


def _contract():
    from data_lake.product_adapter import LakeProductContract  # type: ignore

    return LakeProductContract(
        source=config.LAKE_SOURCE,
        domain=config.LAKE_DOMAIN,
        product_schema_version=config.SCHEMA_VERSION,
        privacy_class=config.LAKE_PRIVACY_CLASS,
        retention_class=config.LAKE_RETENTION_CLASS,
        bronze_schema_version=config.LAKE_BRONZE_SCHEMA_VERSION,
        project_root=config.PROJECT_ROOT,
        data_lake_uri=_lake_uri() or "",
        lineage_filename=config.LINEAGE_FILE,
        datasets=(config.LAKE_DATASET_ARTICLES, config.LAKE_DATASET_HISTORY),
    )


def utc_now_iso() -> str:
    return _ps_mod().utc_now_iso()


def make_record_id(row: dict[str, Any]) -> str:
    return _ps_mod().make_record_id(row, id_fields=config.ID_FIELDS, id_sep=config.ID_SEP)


def news_item_from_bronze(row: dict[str, Any], *, history: bool = False, history_idx: int = 0) -> dict[str, Any]:
    payload = _ps_mod().parse_payload_json(row)
    event_time = str(row.get("event_time") or payload.get("captured_at") or "")
    item: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "id":
            continue
        item[key] = value if isinstance(value, (dict, list)) else str(value or "")
    item.update(
        {
            "headline": str(payload.get("headline") or payload.get("title") or ""),
            "canonical_url": str(payload.get("canonical_url") or payload.get("url") or ""),
            "publisher": str(payload.get("publisher") or payload.get("source") or ""),
            "observed_at": str(payload.get("observed_at") or event_time),
            "capture_kind": str(payload.get("capture_kind") or "rss_article"),
            "updated_at": event_time,
            "event_time": event_time,
            "ingest_run_id": str(row.get("ingest_run_id") or ""),
            "source_record_id": str(row.get("source_record_id") or ""),
            "raw_object_key": str(row.get("raw_object_key") or ""),
        }
    )
    if history:
        item["record_id"] = make_record_id(item) + f"#h{history_idx}"
    else:
        item["record_id"] = make_record_id(item)
    return item


def _history_observation_key(item: dict[str, Any]) -> str:
    """Identify one source observation while ignoring physical lake lineage."""
    physical_fields = {"record_id", "ingest_run_id", "raw_object_key"}
    payload = {key: value for key, value in item.items() if key not in physical_fields}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def deduplicate_history_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact replay duplicates but retain observations from new captures.

    Cumulative history CSVs can be replayed by an older operator command.  The
    source identity and event timestamp remain part of the key, so the same
    article observed at a later capture time is still a distinct history row.
    Physical batch identifiers are excluded because a replay creates a new
    immutable landing/Bronze batch for the same source observation.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = _history_observation_key(item)
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(item)
        normalized["record_id"] = make_record_id(normalized) + f"#h{len(unique)}"
        unique.append(normalized)
    return unique


def _window(min_ingest_date: Optional[str]) -> dict[str, Any]:
    """Only pass the bound when set, so older pinned data-lake-pipelines keep working."""
    return {"min_ingest_date": min_ingest_date} if min_ingest_date else {}


def load_records(
    *, data_lake_uri: Optional[str] = None, min_ingest_date: Optional[str] = None
) -> dict[str, Any]:
    """Latest article rows; ``min_ingest_date`` (YYYY-MM-DD) skips older Bronze partitions."""
    return _ps_mod().load_bronze_dataset(
        _contract(),
        config.LAKE_DATASET_ARTICLES,
        data_lake_uri=data_lake_uri or _lake_uri(),
        latest_only=True,
        id_fields=config.ID_FIELDS,
        id_sep=config.ID_SEP,
        stale_after_hours=config.STALE_AFTER_HOURS,
        item_builder=news_item_from_bronze,
        read_mode=config.LAKE_READ_MODE,
        read_fallback=config.LAKE_READ_FALLBACK,
        **_window(min_ingest_date),
    )


def load_history(
    *, data_lake_uri: Optional[str] = None, min_ingest_date: Optional[str] = None
) -> dict[str, Any]:
    result = _ps_mod().load_bronze_dataset(
        _contract(),
        config.LAKE_DATASET_HISTORY,
        data_lake_uri=data_lake_uri or _lake_uri(),
        latest_only=False,
        id_fields=config.ID_FIELDS,
        id_sep=config.ID_SEP,
        stale_after_hours=config.STALE_AFTER_HOURS,
        item_builder=news_item_from_bronze,
        read_mode=config.LAKE_READ_MODE,
        read_fallback=config.LAKE_READ_FALLBACK,
        **_window(min_ingest_date),
    )
    items = result.get("items")
    if isinstance(items, list):
        result["items"] = deduplicate_history_items(items)
    return result


def get_record(record_id: str, *, data_lake_uri: Optional[str] = None) -> Optional[dict[str, Any]]:
    return _ps_mod().get_record_from_payload(record_id, load_records(data_lake_uri=data_lake_uri))


def paginate(
    items: list[dict[str, Any]], *, limit: int = 50, cursor: Optional[str] = None
) -> tuple[list[dict[str, Any]], Optional[str]]:
    return _ps_mod().paginate(items, limit=limit, cursor=cursor)


def envelope(
    *,
    items: list[dict[str, Any]],
    data_status: str,
    next_cursor: Optional[str] = None,
    retrieved_at: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return _ps_mod().envelope(
        schema_version=config.SCHEMA_VERSION,
        source=config.REPO_NAME,
        items=items,
        data_status=data_status,
        next_cursor=next_cursor,
        retrieved_at=retrieved_at,
        extra=extra,
    )
