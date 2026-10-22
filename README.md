# book-news-scraping

**Tier:** B (catalog label; Big Loop target L3)  
**Owner path:** `bookchaowalit/book-apps/tools/book-news-scraping`

## Purpose

Bounded capture of Thai news from public RSS/Atom feeds (Matichon, NotebookSpec,
Bangkok Post Business, Blognone) plus a read-only `news.v1` data API.

## Entry points

- `scripts/run_feeds.py` -> `news/{matichon,notebookspec,thai_business,thai_tech}_scraper.py`, each a `FeedSpec` for the generic parser/scraper in `news/feed_adapter.py` (text/date/CSV helpers in `news/feed_common.py`)
- Opt-in feeds: `scripts/run_feeds.py --feeds bangkok_post_tech thaiger_business techcrunch_tech` (`news/optional_feeds.py`; not in the default roster)

## Stack

Python

## How to run (local)

```bash
uv sync --frozen --all-extras          # runtime + dev tools + data-lake runtime + sentry extra
uv run python scripts/run_feeds.py --limit 20   # live publisher traffic: run only when approved
bash setup_cron.sh plan      # read-only; prints the data-lake runner entry
bash setup_cron.sh status
```

Adapters: Matichon, Bangkok Post Business, Blognone, NotebookSpec.
Output stays in this repository's `data/exported/`; snapshot and raw files are
replaced atomically (temp file + fsync + `os.replace`). Whether the legacy
book-job-scraping compatibility scheduler still collects the same feeds is not
verified (no such entry in this WSL host's crontab on 2026-10-22) [ต้องยืนยัน].

The approved captures can be replayed into the shared Bronze lake with the
parent operator command:

```bash
task scraping:ingest -- --product news
task scraping:stack -- --require-job-readiness
```

For one bounded collection-to-lake cycle, run the parent control-plane command
with an explicit writable lake path:

```bash
task scraping:news:run -- \
  --lake-uri /absolute/path/to/data/lake \
  --attempts 2 --collector-timeout-seconds 120 --json
```

The command acquires the News source lock, runs the RSS collector, validates
all eight snapshot/history captures before replay, and writes Bronze
idempotently. Cumulative history CSVs are committed as append deltas while the
full capture bytes remain in immutable landing, and the API removes exact
replay duplicates as a defense-in-depth measure. Health checks require every
feed to have a fresh current record and require the read path to stay on
Parquet. If ingest or health fails, bounded retries replay the same validated
capture without hitting RSS again. It does not install cron or enable the API
refresh endpoint.

The read-only `news.v1` API listens on `127.0.0.1:8108` and serves committed
Bronze data only. Consumers must use `GET /v1/records` (or `/v1/history`) and
preserve publisher attribution; they must not read these CSVs directly.

The scheduler plan uses the same control-plane runner and source lock. Review
it with an explicit lake before any installation:

```bash
SOLO_DATA_LAKE_ROOT=/path/to/solo-data-lake \
SOLO_EMPIRE_DATA_LAKE_URI=/absolute/path/to/shared/lake bash setup_cron.sh plan
```

Installation requires `SOLO_EMPIRE_DATA_LAKE_URI` and refuses a missing or
non-writable local path. When approved, `bash setup_cron.sh install` runs the
bounded runner every two hours at minute 15, writes JSON logs, and keeps the
collector lock shared with the domain boundary. It uses the
data-lake `infra/scripts/setup/run-python3.sh` runtime (`SOLO_DATA_LAKE_ROOT`) and checks for `duckdb`,
`feedparser`, and `pyarrow` before installing. The plan command never edits
crontab.

## Polite collection

All four adapters fetch through `news/http.py`: one identifying
`User-Agent` (`book-news-scraping/1.0`), a 30 s timeout, and at most three
attempts with exponential backoff (2 s, 4 s) that retry only timeouts,
connection errors, HTTP 429 (honouring `Retry-After`, capped at 60 s) and 5xx.
403/404 fail immediately. `scripts/run_feeds.py` isolates publishers: a failing
feed is reported as `{"source": ..., "error": "<ExceptionClass>"}` (no payload
text) while the others still run, and the exit code is 1 if any feed failed.
With the `sentry` extra installed and `SENTRY_DSN` set, such a run also sends one
Sentry event naming the failed feeds and exception classes (`news/observability.py`;
frame locals, request bodies and exception messages are scrubbed).

Text cleaning, date parsing and CSV writing are shared in `news/feed_common.py`.
`updated_at` is the entry's own update time and is empty when a feed has none
(feedparser's deprecated `updated` -> `published` fallback is not used; pytest
turns that DeprecationWarning into an error).

The former `news/thai_news_scraper.py` was removed in the 2026-09 upgrade pass:
it imported the retired monorepo `adapters`/`core` packages and never ran from a
standalone checkout. Bangkok Post Business is covered by
`thai_business_scraper.py`. Bangkok Post Tech, Thaiger Business and TechCrunch
are config-only `FeedSpec`s in `news/optional_feeds.py`, run only when named
with `--feeds`: the parent News capture and lake ingest register just the four
default sources. Their fixtures are synthetic RSS 2.0 / WordPress-shaped
documents, so confirm each live feed once before scheduling it. Techsauce is
not added (feed format not confirmed offline).

A new feed is a `FeedSpec` (host, accepted feed paths, timezone, row extras,
file stem, labels) plus a fixture test; parsing, URL policy, writers and the
scheduler class are shared.

## Checks (offline)

```bash
uv sync --frozen --all-extras
uv run ruff check . && uv run ruff format --check .
uv run mypy .                      # gradual config in pyproject.toml
uv run pytest -q --cov             # CI gate: total coverage >= 80%
```

Tests replay fixtures under `tests/fixtures/` and never contact publishers.
`uv.lock` pins the complete dependency set, including the shared
`solo-empire-data-lake` runtime at an exact commit (dev extra; it needs Python
3.11+). The workflow asserts the shared helpers import before testing, so a
missing runtime fails CI instead of skipping the `news.v1` store tests.
`tests/test_news_contract.py` checks capture rows and API items against a copy of
`news-data-contract-v1`. CI (`.github/workflows/ci.yml`, shared
`platform-ci-workflows` v1.1.1) runs the same checks on Python 3.11 and 3.13.

## Boundaries

- **Lake/API boundary:** capture remains owned here; the parent operator owns
  replay orchestration and the shared lake runtime, while this repository owns
  the `news.v1` read-only delivery adapter.
- **Not** coupled to upstream consumer apps. Nested Git repo; commit only inside this tree.
- Never commit `.env`, cookies, session dumps, or scraped PII dumps to Git.

## Limitations (honest)

Publishers may disallow automated access. Only publisher-provided RSS/Atom
captures with canonical URLs and attribution are approved. The API does not
republish article bodies or trigger collection from a read request.

## Related

- Active collection product: `book-job-scraping` (Tier A tool)
- Lake products: `book-crypto-data`, `book-fx-data`, `book-stock-data`, …
- Solo Empire catalog: `repository-catalog/BOOK-DEV-BACKLOG-BD.md` (BD-012)
