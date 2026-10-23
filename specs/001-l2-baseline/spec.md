---
id: SPEC-001
title: L2/L3 baseline for content-news-scraper
status: in review
created: 2026-10-22
owner: bookchaowalit
---

# SPEC-001: L2/L3 baseline

## Document control

| Field | Value |
|---|---|
| Main-only | yes (ADR-0004 v1.1: red run is local, red and green commits pushed together) |
| Maker | Claude session b-data (2026-10-22) |
| Checker / approver | pending (owner) |

## Problem

The Big Loop scorecard (2026-10-22) had this repo at L0: no lockfile (only
`requirements.txt` + `constraints.txt`), no type check, no error reporting, no spec or
KPI plan. Review found two silent failure paths:

1. `write_snapshot` opened `data/exported/<feed>.csv` with `"w"` (truncating it) and
   wrote row by row, and `write_bytes` used `Path.write_bytes`. A collector killed by
   the control plane's timeout, or failing mid-write, left a truncated or empty capture
   where the last good one was, and the control plane replays these files into Bronze.
2. The control plane records only `collector_failed` (it hides collector output on
   purpose), so which feed broke was visible only in the cron log.

## Behaviour

1. Dependencies resolve from the committed `uv.lock` (`[tool.uv] package = false`),
   including the shared `solo-empire-data-lake` runtime pinned by commit (dev extra).
   `requirements.txt`, `requirements-dev.txt` and `constraints.txt` are removed: only the
   README installed from them (the control plane runs the collector with its own Python).
   `requires-python` is 3.11+ because the data-lake runtime needs it.
2. `mypy .` runs in CI (gradual; strict on `news/observability.py`).
3. Raw XML and snapshot CSV are written to a temp file in the same directory, fsynced and
   `os.replace`d; a failure leaves the previous file and no temp file.
4. With `SENTRY_DSN` set and the `sentry` extra installed, a run with failed feeds sends
   one event: `warning` if some failed, `error` if all; the message names the feeds and
   exception classes only. Without a DSN the SDK is never imported.
5. Sentry is initialised with `send_default_pii=False`, `traces_sample_rate=0.0`,
   `include_local_variables=False`, `max_request_body_size="never"` and a `before_send`
   (`scrub_event`) that drops frame `vars`, `request`, `breadcrumbs` and `extra` and
   blanks exception messages (security review 2026-10-22).
6. Capture columns and API items match `news-data-contract-v1` except the pinned known gap.
7. CI fails when total coverage drops below 80%.

## Acceptance

| AC | Given / When / Then | Test |
|---|---|---|
| AC-01 | Given a previous capture, when a snapshot or raw write fails midway, then the previous file is unchanged and no temp file remains; successful writes replace the file | `tests/test_atomic_writes.py` |
| AC-02 | Given `SENTRY_DSN`, when 1 of 2 feeds fails, then one `warning` "news feeds: 1 of 2 failed: matichon_news (RuntimeError)" is sent without payload text; all failed → `error`; clean run or no DSN → nothing; init is scrubbed | `tests/test_observability.py` |
| AC-03 | Capture columns ⊆ contract fields (+ `captured_at`, `feed_title`); API items from fixture captures carry every contract field except the per-feed extras and `source_feed_url`; identity `source|article_id` | `tests/test_news_contract.py` |
| AC-04 | CI on `main` is green on Python 3.11 and 3.13 with the coverage gate | CI run below |

## Red/green log

| AC | Red (sha · command · failure) | Green |
|---|---|---|
| AC-01, AC-02 | `eb6cf37` · `python -m pytest -q tests/test_atomic_writes.py tests/test_observability.py` · snapshot `AssertionError` (previous rows replaced by the partial write), `AttributeError: module 'news.feed_common' has no attribute 'os'`, Sentry never initialised (6 failed, 2 passed) | [run 39756016801](https://github.com/bookchaowalit/content-news-scraper/actions/runs/39756016801) (success, 3.11 + 3.13, `3d001b1`) |

## Contract findings (news-data-contract-v1)

- `source_feed_url` is a contract record field, but neither the capture nor
  `news_data.store.news_item_from_bronze` produces it; the feed URL is carried as
  `source_url`. Pinned in `KNOWN_GAPS`; resolve by aliasing in the API item or by
  dropping the field from the contract (architecture-docs owner).
- `feed_title` and `captured_at` are capture-only columns not listed by the contract
  (`captured_at` becomes the Bronze `event_time` / `observed_at`).
- Identity, port 8108, schema `news.v1`, datasets `articles` / `articles_history` and the
  envelope keys match. Lake-first path: exact landing bytes and the Bronze manifest are
  produced by the parent control plane, not this repo.

## Schedule (D6: Railway cron, live 2026-10-23)

Owner decision D6 (2026-10-23) put scheduled data jobs on Railway cron. Railway project
`data-schedules`, service `news-capture`, cron `15 */2 * * *` UTC (every 2 hours, inside the
8-hour freshness SLO), built from `deploy/railway-cron/Dockerfile` (data-lake-pipelines pinned by
commit + this collector). Each run is `scripts/scheduled_capture.py`: the control plane's
`run_news_capture.py` (shared lock, collector → validate → Bronze replay → per-feed freshness gate)
against the R2 lake `s3://solo-empire-portfolio/portfolio-demo/free-cloud-e2e-001`, counts-only log,
Sentry project `content-news-scraper` for a failed run (the collector reports feed failures itself),
and the uptime Worker heartbeat `news-capture` (alert after 5 h). Details and rollback:
`deploy/railway-cron/README.md`.

First controlled run 2026-10-23 16:14 UTC: `status=ok`, 4 feeds (Matichon 50, Notebookspec 25,
Bangkok Post Business 10, Blognone 10), 95 current records, 32 objects under the news-only
prefixes, identity `(source, article_id)` unique, no empty core field. `setup_cron.sh` was never
installed on any checked host and is kept only for a local lake; the hosted job replaces it.

## Out of scope

Live captures, lake writes, installing any schedule, starting the API, fixing the
`source_feed_url` gap, and the backlog in `docs/UPGRADE-PLAN.md`.
