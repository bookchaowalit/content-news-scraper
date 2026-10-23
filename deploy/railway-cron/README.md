# Railway cron: `news-capture` (owner decision D6)

Replaces the never-installed `setup_cron.sh` crontab line. Railway project `data-schedules`,
service `news-capture`, cron `15 */2 * * *` (UTC), built from this repository with
`deploy/railway-cron/Dockerfile`. Each run executes `scripts/scheduled_capture.py`:
data-lake-pipelines' `run_news_capture.py` (collector → validate → Bronze replay → per-feed
freshness gate) against the R2 lake, prints counts only, sends a failed run to Sentry (project
`content-news-scraper`) and posts the heartbeat `news-capture` to the uptime Worker (alert after 5 h).

| Variable | Value |
|---|---|
| `SOLO_EMPIRE_DATA_LAKE_URI` | `s3://solo-empire-portfolio/portfolio-demo/free-cloud-e2e-001` (writes only `bronze/domain=news`, `landing/source=book-news-scraping`, `control/*/source=book-news-scraping`) |
| `DATA_LAKE_CLOUD_WRITE_ENABLED` | `true` |
| `DATA_LAKE_S3_ENDPOINT`, `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION=auto` | bucket-scoped R2 key from Infisical `/job-data` (bucket `solo-empire-portfolio` only) |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT=production` | Sentry project `content-news-scraper` (org `personal-yu0`) |
| `HEARTBEAT_TOKEN` | Infisical `/monitoring` |

Deploy (from the repository root, Railway CLI linked to `data-schedules` / `news-capture`):

```bash
npx -y @railway/cli@latest up --detach -s news-capture
```

Bump `DATA_LAKE_PIPELINES_REF` in the Dockerfile when the control plane changes.

Turn it off: remove the cron schedule of `news-capture` in Railway (nothing else runs it).
Undo the data: delete the three news prefixes above from the bucket; no other dataset shares them.
