"""Opt-in Sentry for the RSS collector (``scripts/run_feeds.py``).

Off unless ``SENTRY_DSN`` is set and the ``sentry`` extra is installed. A run in
which feeds failed sends one event naming the feeds and the exception class only:
publisher payloads, URLs and error messages are never attached.

Scrubbing (security review 2026-10-22): ``include_local_variables`` is off, request
bodies are never sent, and :func:`scrub_event` (``before_send``) drops frame
``vars``, request data, breadcrumbs and extras and blanks exception messages, so
an uncaught crash reported by Sentry's excepthook carries the type only.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from importlib import import_module
from types import ModuleType
from typing import Any


def _strip_frames(container: Any) -> None:
    if not isinstance(container, dict):
        return
    for item in container.get("values") or []:
        if not isinstance(item, dict):
            continue
        for frame in (item.get("stacktrace") or {}).get("frames") or []:
            if isinstance(frame, dict):
                frame.pop("vars", None)


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """``before_send``: drop locals, request data and free text that may hold payloads."""
    for key in ("request", "breadcrumbs", "extra"):
        event.pop(key, None)
    exception = event.get("exception")
    _strip_frames(exception)
    if isinstance(exception, dict):
        for item in exception.get("values") or []:
            if isinstance(item, dict):
                item["value"] = ""
    _strip_frames(event.get("threads"))
    return event


def init_sentry(job: str) -> ModuleType | None:
    """Initialise Sentry for one run; return the SDK, or None when it is off."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return None
    try:
        sdk = import_module("sentry_sdk")
    except ImportError:
        return None
    sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "local"),
        send_default_pii=False,
        traces_sample_rate=0.0,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
    )
    sdk.set_tag("job", job)
    return sdk


def report_feed_failures(sdk: ModuleType | None, results: Iterable[Mapping[str, Any]], planned: int) -> None:
    """One event when feeds failed: ``error`` if all of them, else ``warning``."""
    failed = [r for r in results if "error" in r]
    if sdk is None or not failed:
        return
    names = ", ".join(f"{r.get('source')} ({r.get('error')})" for r in failed)
    level = "error" if len(failed) >= planned else "warning"
    sdk.capture_message(f"news feeds: {len(failed)} of {planned} failed: {names}", level=level)
    sdk.flush(timeout=5)
