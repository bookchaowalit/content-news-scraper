#!/usr/bin/env python3
"""Hosted news schedule (owner decision D6: Railway cron, every 2 hours).

Runs data-lake-pipelines' ``run_news_capture.py`` once against the lake named by
``SOLO_EMPIRE_DATA_LAKE_URI`` (collector -> validate -> Bronze replay -> freshness
gate), prints counts only, reports a failed run to Sentry and posts the result to
the uptime Worker heartbeat ``news-capture``. The collector subprocess inherits
``SENTRY_DSN`` and reports its own feed failures (news/observability.py).

Exit code: 0 when the cycle status is ``ok``, otherwise 1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news.observability import init_sentry  # noqa: E402

HEARTBEAT_URL = "https://solo-empire-monitor.bookchaowalit.workers.dev/heartbeat/news-capture"
# The control plane bounds the collector at 120 s per attempt (2 attempts); this caps the rest.
CYCLE_TIMEOUT_SECONDS = 900

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
Poster = Callable[[str, str, dict[str, Any]], None]


class ConfigError(RuntimeError):
    """The schedule is missing required configuration."""


def build_command(env: Mapping[str, str]) -> list[str]:
    lake_uri = env.get("SOLO_EMPIRE_DATA_LAKE_URI", "").strip()
    if not lake_uri:
        raise ConfigError("SOLO_EMPIRE_DATA_LAKE_URI is not set")
    root = Path(env.get("PIPELINES_ROOT", "/app/data-lake-pipelines"))
    python = env.get("PIPELINES_PYTHON") or str(root / ".venv" / "bin" / "python")
    runner = root / "infra" / "scripts" / "data_lake" / "run_news_capture.py"
    return [python, str(runner), "--json", "--lake-uri", lake_uri]


def summarize(cycle: Mapping[str, Any]) -> dict[str, Any]:
    """Status and counts only: no titles, URLs or feed payloads reach the log."""
    health = cycle.get("health") or {}
    feeds = health.get("feeds") or {}
    return {
        "status": cycle.get("status"),
        "error": cycle.get("error"),
        "schema_version": cycle.get("schema_version"),
        "data_status": health.get("data_status"),
        "record_count": health.get("record_count"),
        "committed": sum(int(c.get("record_count") or 0) for c in cycle.get("committed") or []),
        "feeds": {name: f.get("record_count") for name, f in feeds.items()},
    }


def run_cycle(env: Mapping[str, str], runner: Runner) -> tuple[bool, str]:
    """Run one cycle; return (ok, reason). The reason never contains collector output."""
    try:
        result = runner(
            build_command(env), capture_output=True, text=True, timeout=CYCLE_TIMEOUT_SECONDS, env=dict(env)
        )
    except subprocess.TimeoutExpired:
        return False, f"news capture timed out after {CYCLE_TIMEOUT_SECONDS}s"
    try:
        cycle = json.loads(result.stdout)
    except (TypeError, ValueError):
        cycle = None
    if isinstance(cycle, dict):
        print(json.dumps(summarize(cycle), sort_keys=True))
    error = cycle.get("error") if isinstance(cycle, dict) else None
    detail = f", {error}" if error else ""
    if result.returncode != 0:
        return False, f"news capture failed (exit {result.returncode}{detail})"
    status = cycle.get("status") if isinstance(cycle, dict) else None
    if status != "ok":
        return False, f"news capture finished with status {status}"
    return True, "ok"


def post_heartbeat(url: str, token: str, body: dict[str, Any]) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        # Cloudflare rejects the default Python-urllib agent on workers.dev.
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "content-news-scraper-scheduled-capture/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed https URL
        response.read()


def main(
    env: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    post: Poster = post_heartbeat,
    sentry: Any = None,
) -> int:
    env = dict(os.environ) if env is None else env
    if sentry is None:
        sentry = init_sentry("news-scheduled-capture")
    try:
        ok, reason = run_cycle(env, runner)
    except ConfigError as exc:
        ok, reason = False, str(exc)
    failures = [] if ok else [reason]

    token = env.get("HEARTBEAT_TOKEN", "").strip()
    if token:
        try:
            post(HEARTBEAT_URL, token, {"ok": ok, "failed": [] if ok else ["capture"]})
        except urllib.error.HTTPError as exc:
            failures.append(f"heartbeat post failed (HTTP {exc.code})")
        except OSError as exc:
            failures.append(f"heartbeat post failed ({type(exc).__name__})")
    else:
        print("HEARTBEAT_TOKEN not set; heartbeat skipped", file=sys.stderr)

    for message in failures:
        print(message, file=sys.stderr)
        if sentry is not None:
            sentry.capture_message(message, level="error")
    if failures and sentry is not None:
        sentry.flush(timeout=5)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
