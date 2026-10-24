---
title: KPI and Instrumentation Plan — book-news-scraping
created: 2026-10-22
updated: 2026-10-22
status: approved
template: architecture-docs/templates/sdlc/kpi-and-instrumentation-plan.md
---

# book-news-scraping — KPI and Instrumentation Plan

One plan for the news domain product. Honest scope: no schedule is installed, so live
baselines are not measured yet.

## Document control

| Field | Value |
|---|---|
| Project / product ID | book-news-scraping (catalog), repo `content-news-scraper` |
| Version | 0.1 |
| Status | draft |
| Metric owner | bookchaowalit (owner) |
| AI maker | Claude session b-data, 2026-10-22 |
| AI reviewer | independent Claude reviewer subagent (`solo:solo-reviewer`, Sonnet, read-only, no maker context), 2026-10-24: approved (see Approval) |
| Charter objectives | Roadmap `data-scrapers.yaml` goals nws-g1..nws-g4 (reproducible CI, schedule observed, docs truthful, consumer verified) |
| Analytics / data source of truth | Bronze `articles` / `articles_history` (event_time, row counts) via the `news.v1` API and the parent coverage report; collector JSON output; Sentry (opt-in, no DSN yet) |
| Dashboard | none yet [ต้องยืนยัน] |
| Next review | when D6 is decided and the schedule is installed |

## KPI tree

```text
OBJ-01 Fresh, attributed Thai news in the lake for briefing/research consumers
  └─ KPI-O-01 Feeds fresh within the 8-hour SLO
       ├─ KPI-L-01 Feed failure rate per collector run
       ├─ KPI-L-02 Articles captured per feed per run
       ├─ KPI-G-01 Contract violations (must stay 0)
       └─ KPI-G-02 Consumers reading CSVs instead of news.v1 (must stay 0)
```

## KPI definitions

| KPI ID | Type | Name | Objective | Formula | Unit | Min volume | Segment | Data source | Baseline | Target | Alert threshold | Cadence | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KPI-O-01 | outcome | Feeds within freshness SLO | OBJ-01 | feeds whose newest Bronze `event_time` is ≤ 8h old / 4 contracted feeds | % | 4 feeds | per publisher label | parent `task scraping:monitor` / coverage report; API `/v1/records` | not yet measured (no schedule) | 100% for 7 consecutive days by 2026-12-31 (roadmap nws-g2) | any feed > 8h | every 2h run | owner |
| KPI-L-01 | leading | Feed failure rate | OBJ-01 | failed feeds / feeds run | % | ≥ 12 feed-runs (3 runs) | per feed | collector `--json` results (`error` entries), Sentry events | not yet measured | < 5% [ต้องยืนยัน] | same feed failing 3 runs in a row | per run | owner |
| KPI-L-02 | leading | Articles per feed per run | OBJ-01 | `count` in the collector result | articles | 1 run | per feed | collector result, snapshot CSV rows | fixtures only (offline); live not measured | ≥ 1 per run, ≤ 50 (limit) | 0 on a successful run | per run | owner |
| KPI-G-01 | guardrail | Contract violations | OBJ-01 | capture/API fields outside `news-data-contract-v1`, beyond the pinned known gap | count | n/a | all feeds | CI `tests/test_news_contract.py` | 0 (+1 pinned gap `source_feed_url`, 2026-10-22) | must stay 0 | any > 0 fails CI | every push | owner |
| KPI-G-02 | guardrail | CSV consumers | OBJ-01 | consumers reading `data/exported/*.csv` directly | count | n/a | all consumers | consumer review (roadmap nws-g4) | not yet measured [ต้องยืนยัน] | 0 | any > 0 | at review | owner |

## Event and data specification

| Event / field | Trigger | Properties | Personal data? | Emitted by | Requirement | Status |
|---|---|---|---|---|---|---|
| Collector result `{"source", "count"}` / `{"source", "error"}` | each feed in a run | feed key, count or exception class | no | `scripts/run_feeds.py` | — | implemented |
| Sentry "news feeds: N of M failed: …" | a run with failed feeds | level, feed keys + exception classes, tag `job=news-feeds` | no (scrubbed) | `news/observability.py` | SPEC-001 AC-02 | implemented, not live |
| Bronze `articles` manifest / `event_time` | control-plane replay | row count, checksum, event_time | author names are public bylines (privacy class `public`) | data-lake-pipelines | roadmap nws-g2 | implemented upstream, not scheduled |

## Dashboards and alerts

| Dashboard / alert | KPIs | Audience | Location | Refresh | Alert channel | Status |
|---|---|---|---|---|---|---|
| Parent coverage/monitor report | KPI-O-01, KPI-L-02 | owner | `task scraping:monitor` | per run | — | available, not scheduled |
| Sentry issue stream | KPI-L-01 | owner | Sentry (project not created) | live | Sentry email [ต้องยืนยัน] | planned |

## Instrumentation verification (before G10)

| # | Check | Evidence | Result |
|---|---|---|---|
| 1 | Each failed-feed run sends one event | `tests/test_observability.py` (fake SDK) | pass (offline) |
| 2 | Counts reconcile with the collector result | same tests | pass (offline) |
| 3 | No PII/payload in events | scrub + message tests | pass |
| 4 | Dashboard renders KPIs | — | not started |
| 5 | Alert reaches the owner | needs Sentry project + DSN (owner action) | not started |
| 6 | Baselines captured | needs the installed schedule (D6) | waived until D6 |
| 7 | Consent | n/a (no end users tracked) | n/a |

## Change history of definitions

| Date | KPI ID | Change | Reason | Baseline restated? | Approved by |
|---|---|---|---|---|---|
| 2026-10-22 | all | first draft | Big Loop L3 | n/a | pending |

## Approval (2026-10-24)

| Field | Value |
|---|---|
| Checker | independent Claude reviewer subagent (`solo:solo-reviewer`, Sonnet, read-only, no maker context) |
| Approver | AI approval under the owner's process (approvals by the owner or AI with evidence; maker and checker are different agents). Recorded by Claude session oa-remainder on the owner's instruction "ทำที่เหลือให้หน่อย" (2026-10-24) |
| Verdict | **approved** |
| Evidence | news/observability.py job tag; scripts/run_feeds.py --json, limit 50; tests/test_news_contract.py KNOWN_GAPS; Sentry and schedule marked not live (plan understates the 2026-10-23 Railway schedule, not an overclaim). |
