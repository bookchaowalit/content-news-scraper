# book-news-scraping — Product brief

**Slug:** `bookchaowalit/content-news-scraper`
**Catalog tier:** B (Big Loop target L3) · **Updated:** 2026-10-22
**Status:** news domain producer (publisher RSS/Atom capture) and `news.v1` read-only API adapter; not scheduled

## Purpose

Bounded capture of Thai news from four approved publisher feeds (Matichon, Bangkok Post
Business, Blognone, NotebookSpec) into `data/exported/`, which the parent data-lake
control plane replays into Bronze `articles` / `articles_history`; plus the read-only
`news.v1` API on `127.0.0.1:8108` that serves those Bronze rows with publisher
attribution. The API never calls publishers and never republishes article bodies.

## Runtime status (verified 2026-10-22)

| What | Status |
|---|---|
| Collector entry point | `scripts/run_feeds.py` (default roster: the four contracted feeds; `--feeds` adds the opt-in Bangkok Post Tech / Thaiger / TechCrunch specs). Exit 1 when any feed failed |
| Who runs it | data-lake-pipelines `infra/scripts/data_lake/run_news_capture.py` (`task scraping:news:run`) runs it as a subprocess, then validates and replays the captures into Bronze |
| Schedule | None installed. `setup_cron.sh install` would add a 2-hourly (minute 15) crontab entry for that control-plane runner; this WSL host's crontab has no such entry on 2026-10-22 (`setup_cron.sh status`: NOT INSTALLED). Windows Task Scheduler and the legacy book-job-scraping compatibility collector cannot be verified from here [ต้องยืนยัน] |
| API | `python -m news_data.api` on `127.0.0.1:8108` (GET only; refresh returns 403 unless gated on). Not hosted anywhere; no evidence it is running [ต้องยืนยัน] |
| Hosted deployment | None |
| Error reporting | Sentry, opt-in: install the `sentry` extra and set `SENTRY_DSN`. A run with failed feeds sends one event (`warning`, or `error` if all failed) naming the feeds and exception classes; locals, request bodies, breadcrumbs and exception messages are scrubbed. No DSN configured yet [ต้องยืนยัน] |
| Contract | `news-data-contract-v1` (`news.v1`, port 8108, identity `source|article_id`); offline check in `tests/test_news_contract.py`. Known gap: `source_feed_url` is listed by the contract but not produced (the feed URL is in `source_url`) |
| Quality gates in CI | ruff, ruff format, mypy (gradual; strict on `news/observability.py`), data-lake import check, offline pytest with coverage >= 80%, on Python 3.11 and 3.13, plus the shared security scan |

## Adapters

- `news/matichon_scraper.py`, `news/thai_business_scraper.py`, `news/thai_tech_scraper.py`,
  `news/notebookspec_scraper.py`: each a `FeedSpec` for the shared parser in `news/feed_adapter.py`.
- Capture files (raw XML, snapshot CSV) are replaced atomically; history CSVs are appended.

## Limits

- Publishers may disallow automated access; only publisher-provided RSS/Atom with
  canonical URLs and attribution is approved.
- Freshness depends on a schedule that is not installed (owner decision D6).

## Docs

- Spec: `specs/001-l2-baseline/spec.md` · KPI plan: `docs/measurement/KPI-PLAN.md`
- Backlog: `docs/UPGRADE-PLAN.md` · Product card: `DOCPACK/`
