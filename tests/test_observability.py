"""Failed feeds in a collector run reach Sentry (opt-in), scrubbed.

``run_feeds`` isolates each publisher and exits 1 when any failed, but the
parent control plane only records ``collector_failed``: which feed broke was
visible nowhere outside the cron log. With ``SENTRY_DSN`` set, a run with failed
feeds sends one event naming the feeds and the exception class only (publisher
payloads must not leak), and the SDK is initialised so that frame locals,
request bodies and exception messages are never sent.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_feeds

SECRET = "token=abc123"


class FakeLoggingIntegration:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakeSentry(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("sentry_sdk")
        self.init_kwargs: dict[str, Any] | None = None
        self.messages: list[tuple[str, str]] = []
        self.tags: dict[str, str] = {}

    def init(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def capture_message(self, message: str, level: str = "info") -> None:
        self.messages.append((level, message))

    def flush(self, timeout: float | None = None) -> None:
        pass


class Broken:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def run(self) -> list[dict[str, Any]]:
        raise RuntimeError(f"publisher payload {SECRET}")


class Working:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def run(self) -> list[dict[str, Any]]:
        return [{"source": "working", "count": 3}]


@pytest.fixture
def fake_sentry(monkeypatch):
    sdk = FakeSentry()
    logging_module = types.ModuleType("sentry_sdk.integrations.logging")
    logging_module.LoggingIntegration = FakeLoggingIntegration  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", sdk)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.logging", logging_module)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    return sdk


def _main(monkeypatch, tmp_path, feeds) -> int:
    monkeypatch.setattr(run_feeds, "FEEDS", feeds)
    monkeypatch.setattr(sys, "argv", ["run_feeds.py", "--output-dir", str(tmp_path)])
    return run_feeds.main()


def test_failed_feed_reaches_sentry_without_payload(fake_sentry, monkeypatch, tmp_path):
    code = _main(monkeypatch, tmp_path, (("matichon_news", Broken), ("thai_tech_news", Working)))
    assert code == 1
    assert fake_sentry.messages == [("warning", "news feeds: 1 of 2 failed: matichon_news (RuntimeError)")]
    assert fake_sentry.tags.get("job") == "news-feeds"
    assert SECRET not in repr(fake_sentry.messages)


def test_all_feeds_failing_is_an_error(fake_sentry, monkeypatch, tmp_path):
    assert _main(monkeypatch, tmp_path, (("a", Broken), ("b", Broken))) == 1
    assert [level for level, _ in fake_sentry.messages] == ["error"]


def test_clean_run_sends_nothing(fake_sentry, monkeypatch, tmp_path):
    assert _main(monkeypatch, tmp_path, (("thai_tech_news", Working),)) == 0
    assert fake_sentry.messages == []
    assert fake_sentry.init_kwargs is not None


def test_without_dsn_nothing_is_initialised(fake_sentry, monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DSN")
    _main(monkeypatch, tmp_path, (("a", Broken),))
    assert fake_sentry.init_kwargs is None
    assert fake_sentry.messages == []


def test_init_is_scrubbed(fake_sentry, monkeypatch, tmp_path):
    _main(monkeypatch, tmp_path, (("thai_tech_news", Working),))
    kwargs = fake_sentry.init_kwargs
    assert kwargs is not None
    assert kwargs["send_default_pii"] is False
    assert kwargs["traces_sample_rate"] == 0.0
    assert kwargs["environment"] == "test"
    assert kwargs["include_local_variables"] is False
    assert kwargs["max_request_body_size"] == "never"
    event = {
        "request": {"url": f"https://example.test/?{SECRET}"},
        "breadcrumbs": {"values": [{"message": SECRET}]},
        "extra": {"payload": SECRET},
        "exception": {
            "values": [
                {
                    "type": "FeedFetchError",
                    "value": SECRET,
                    "stacktrace": {"frames": [{"function": "fetch_bytes", "vars": {"url": SECRET}}]},
                }
            ]
        },
        "threads": {"values": [{"stacktrace": {"frames": [{"vars": {"raw": SECRET}}]}}]},
    }
    cleaned = kwargs["before_send"](event, {})
    assert cleaned["exception"]["values"][0]["type"] == "FeedFetchError"
    assert SECRET not in repr(cleaned)


def test_init_turns_off_log_events_and_log_breadcrumbs(fake_sentry, monkeypatch, tmp_path):
    # A logger.error/exception (ours or httpx/urllib3) must not become an event carrying
    # free log text (feed URLs, payloads): the logging integration has every level off.
    _main(monkeypatch, tmp_path, (("thai_tech_news", Working),))
    kwargs = fake_sentry.init_kwargs
    assert kwargs is not None
    logging = [i for i in kwargs["integrations"] if isinstance(i, FakeLoggingIntegration)]
    assert len(logging) == 1
    assert logging[0].kwargs == {"level": None, "event_level": None, "sentry_logs_level": None}


def test_sentry_stays_off_without_the_logging_integration(fake_sentry, monkeypatch):
    # Fail closed: if log capture cannot be turned off, do not initialise at all.
    from news.observability import init_sentry

    monkeypatch.delitem(sys.modules, "sentry_sdk.integrations.logging")
    assert init_sentry("news-feeds") is None
    assert fake_sentry.init_kwargs is None


def test_scrub_drops_logentry():
    from news.observability import scrub_event

    event = {
        "level": "error",
        "logger": "httpx",
        "logentry": {
            "message": "HTTP Request: GET %s",
            "params": [f"https://example.test/feed?{SECRET}"],
            "formatted": f"HTTP Request: GET https://example.test/feed?{SECRET}",
        },
    }
    cleaned = scrub_event(event, {})
    assert "logentry" not in cleaned
    assert SECRET not in repr(cleaned)
    assert cleaned["level"] == "error"


def test_scrub_keeps_only_the_reporters_own_message(fake_sentry, monkeypatch, tmp_path):
    from news.observability import scrub_event

    _main(monkeypatch, tmp_path, (("matichon_news", Broken), ("thai_tech_news", Broken)))
    ((_, own),) = fake_sentry.messages
    assert own == "news feeds: 2 of 2 failed: matichon_news (RuntimeError), thai_tech_news (RuntimeError)"
    assert scrub_event({"message": own}, {})["message"] == own

    foreign: tuple[object, ...] = (
        f"HTTP Request: GET https://example.test/feed?{SECRET}",
        f"news feeds: 1 of 2 failed: matichon_news (publisher payload {SECRET})",
        "news feeds: 1 of 2 failed: matichon_news (RuntimeError)\nmore text",
        "news capture failed (exit 1, Traceback: boom)",
        "",
        {"formatted": SECRET},
    )
    for message in foreign:
        cleaned = scrub_event({"message": message, "level": "error"}, {})
        assert "message" not in cleaned, message
        assert cleaned["level"] == "error"
