"""Hosted schedule wrapper (owner decision D6: Railway cron): offline, nothing is posted."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scheduled_capture as sc  # noqa: E402

from news.observability import scrub_event  # noqa: E402

ENV = {
    "SOLO_EMPIRE_DATA_LAKE_URI": "s3://bucket/lake",
    "PIPELINES_ROOT": "/app/data-lake-pipelines",
    "HEARTBEAT_TOKEN": "hb-test",
}

OK_CYCLE = {
    "status": "ok",
    "schema_version": "news.v1",
    "committed": [{"dataset": "articles", "record_count": 50, "title": "never printed"}],
    "health": {
        "data_status": "ok",
        "record_count": 95,
        "feeds": {"Matichon": {"record_count": 50, "status": "ok", "latest_observed_at": "x"}},
    },
}


class FakeSentry:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def capture_message(self, message: str, level: str) -> None:
        self.messages.append((message, level))

    def flush(self, timeout: int) -> None:
        pass


def completed(code: int, payload: Any) -> subprocess.CompletedProcess[str]:
    out = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr="")


def run(result: Any, env: dict[str, str] | None = None) -> tuple[int, list[dict[str, Any]], FakeSentry]:
    beats: list[dict[str, Any]] = []
    sentry = FakeSentry()

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if isinstance(result, BaseException):
            raise result
        return result

    def post(url: str, token: str, body: dict[str, Any]) -> None:
        beats.append({"url": url, "token": token, "body": body})

    code = sc.main(env=env or ENV, runner=runner, post=post, sentry=sentry)
    return code, beats, sentry


def test_command_runs_the_control_plane_against_the_configured_lake() -> None:
    cmd = sc.build_command(ENV)
    assert cmd[0] == "/app/data-lake-pipelines/.venv/bin/python"
    assert cmd[1] == "/app/data-lake-pipelines/infra/scripts/data_lake/run_news_capture.py"
    assert cmd[cmd.index("--lake-uri") + 1] == "s3://bucket/lake"
    assert "--json" in cmd


def test_command_refuses_to_run_without_a_lake_uri() -> None:
    with pytest.raises(sc.ConfigError):
        sc.build_command({"PIPELINES_ROOT": "/app/data-lake-pipelines"})


def test_ok_cycle_beats_ok_and_reports_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    code, beats, sentry = run(completed(0, OK_CYCLE))
    assert code == 0
    assert beats == [{"url": sc.HEARTBEAT_URL, "token": "hb-test", "body": {"ok": True, "failed": []}}]
    assert sentry.messages == []
    printed = capsys.readouterr().out
    assert "never printed" not in printed
    assert '"Matichon": 50' in printed


def test_failed_collector_beats_failure_and_reports_to_sentry() -> None:
    code, beats, sentry = run(completed(2, "not json"))
    assert code == 1
    assert beats[0]["body"] == {"ok": False, "failed": ["capture"]}
    assert sentry.messages and sentry.messages[0][1] == "error"
    assert "exit 2" in sentry.messages[0][0]


def test_non_ok_status_is_a_failure_even_with_exit_zero() -> None:
    stale = dict(OK_CYCLE, status="stale")
    code, beats, sentry = run(completed(0, stale))
    assert code == 1
    assert beats[0]["body"] == {"ok": False, "failed": ["capture"]}
    assert "stale" in sentry.messages[0][0]


def test_failed_cycle_names_its_error_code() -> None:
    failed = {"status": "failed", "schema_version": "news.v1", "attempts": 2, "error": "ingest_write_failed"}
    code, _, sentry = run(completed(1, failed))
    assert code == 1
    assert "ingest_write_failed" in sentry.messages[0][0]


def test_heartbeat_http_error_names_the_status() -> None:
    sentry = FakeSentry()

    def post(url: str, token: str, body: dict[str, Any]) -> None:
        raise sc.urllib.error.HTTPError(url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    code = sc.main(env=ENV, runner=lambda cmd, **kw: completed(0, OK_CYCLE), post=post, sentry=sentry)
    assert code == 1
    assert "HTTP 403" in sentry.messages[0][0]


def test_timeout_is_a_failure() -> None:
    code, beats, sentry = run(subprocess.TimeoutExpired(cmd="x", timeout=1))
    assert code == 1
    assert beats[0]["body"]["ok"] is False
    assert "timed out" in sentry.messages[0][0]


def test_missing_heartbeat_token_skips_the_beat_but_still_runs() -> None:
    env = {k: v for k, v in ENV.items() if k != "HEARTBEAT_TOKEN"}
    code, beats, _ = run(completed(0, OK_CYCLE), env=env)
    assert code == 0
    assert beats == []


def test_failed_heartbeat_post_fails_the_run() -> None:
    sentry = FakeSentry()

    def post(url: str, token: str, body: dict[str, Any]) -> None:
        raise OSError("network down")

    code = sc.main(env=ENV, runner=lambda cmd, **kw: completed(0, OK_CYCLE), post=post, sentry=sentry)
    assert code == 1
    assert "heartbeat" in sentry.messages[0][0]


def _survives_scrub(message: str) -> bool:
    return scrub_event({"message": message}, {}).get("message") == message


def test_collector_free_text_never_reaches_the_sentry_message() -> None:
    # The cycle JSON comes from another process: only short snake_case codes are passed on.
    leaky = {"status": "failed", "error": "Traceback ... GET https://x.test/?token=abc123"}
    code, _, sentry = run(completed(1, leaky))
    assert code == 1
    ((message, _),) = sentry.messages
    assert "token" not in message
    assert message == "news capture failed (exit 1, unrecognised)"

    _, _, sentry = run(completed(0, dict(OK_CYCLE, status="see https://x.test/?token=abc123")))
    ((message, _),) = sentry.messages
    assert message == "news capture finished with status unrecognised"


def test_every_scheduled_capture_message_survives_the_scrubber() -> None:
    # scrub_event keeps only known message formats; each real reporter message must match.
    messages = []
    for result in (
        completed(2, "not json"),
        completed(0, dict(OK_CYCLE, status="stale")),
        completed(1, {"status": "failed", "error": "ingest_write_failed"}),
        completed(1, {"status": "failed", "error": "Free text, not a code"}),
        subprocess.TimeoutExpired(cmd="x", timeout=1),
    ):
        messages += [m for m, _ in run(result)[2].messages]
    _, _, sentry = run(completed(0, OK_CYCLE), env={"PIPELINES_ROOT": "/x", "HEARTBEAT_TOKEN": "hb"})
    messages += [m for m, _ in sentry.messages]
    for exc in (sc.urllib.error.HTTPError("u", 403, "Forbidden", {}, None), OSError("down")):  # type: ignore[arg-type]
        sentry = FakeSentry()

        def post(url: str, token: str, body: dict[str, Any], exc: Exception = exc) -> None:
            raise exc

        sc.main(env=ENV, runner=lambda cmd, **kw: completed(0, OK_CYCLE), post=post, sentry=sentry)
        messages += [m for m, _ in sentry.messages]

    assert len(messages) == 8, messages
    assert [m for m in messages if not _survives_scrub(m)] == []
