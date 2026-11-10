"""Opt-in Sentry for the RSS collector (``scripts/run_feeds.py``).

Off unless ``SENTRY_DSN`` is set and the ``sentry`` extra is installed. A run in
which feeds failed sends one event naming the feeds and the exception class only:
publisher payloads, URLs and error messages are never attached.

Scrubbing (security review 2026-10-22): ``include_local_variables`` is off, request
bodies are never sent, and :func:`scrub_event` (``before_send``) drops frame
``vars``, request data, breadcrumbs and extras and blanks exception messages, so
an uncaught crash reported by Sentry's excepthook carries the type only.

Log text is free text (feed URLs with query strings, payloads, tokens), so it never
becomes an event or a breadcrumb: init installs the logging integration with every
level off (and stays off if that integration cannot be loaded), and
:func:`scrub_event` drops ``logentry`` and any ``message`` that is not one of the
known reporter formats (:func:`report_feed_failures`, ``scripts/scheduled_capture.py``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from importlib import import_module
from types import ModuleType
from typing import Any

_NAME = r"[A-Za-z0-9_.-]{1,64}"
_EXC = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_CODE = r"[a-z][a-z0-9_]{0,47}"
# Every message this repository sends, built only from feed names, counts, exception
# class names, HTTP status codes and snake_case codes (see :func:`safe_code`).
_REPORTED_MESSAGE = re.compile(
    "|".join(
        (
            rf"news feeds: \d{{1,4}} of \d{{1,4}} failed: {_NAME} \({_EXC}\)(?:, {_NAME} \({_EXC}\))*",
            r"news capture timed out after \d{1,6}s",
            rf"news capture failed \(exit -?\d{{1,4}}(?:, {_CODE})?\)",
            rf"news capture finished with status {_CODE}",
            r"SOLO_EMPIRE_DATA_LAKE_URI is not set",
            r"heartbeat post failed \(HTTP \d{3}\)",
            rf"heartbeat post failed \({_EXC}\)",
        )
    )
)


def safe_code(value: object) -> str:
    """``value`` if it is a short snake_case code, else ``"unrecognised"`` (no free text)."""
    return value if isinstance(value, str) and re.fullmatch(_CODE, value) else "unrecognised"


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
    for key in ("request", "breadcrumbs", "extra", "logentry"):
        event.pop(key, None)
    message = event.get("message")
    if not (isinstance(message, str) and _REPORTED_MESSAGE.fullmatch(message)):
        event.pop("message", None)
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
        logging_integration = import_module("sentry_sdk.integrations.logging").LoggingIntegration
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
        # No log record becomes an event, a breadcrumb or a Sentry log.
        integrations=[logging_integration(level=None, event_level=None, sentry_logs_level=None)],
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
