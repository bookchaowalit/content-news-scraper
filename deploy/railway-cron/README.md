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

Deploy: from Git only. A push to `main` runs CI, and its `deploy` job (platform-ci-workflows
`deploy-railway.yml` v1.3.0, `mode: deploy`) asks Railway to build exactly that commit. The service
is linked to this repository with **no branch trigger**, so nothing else deploys it. The repository
secret `RAILWAY_TOKEN` is the `data-schedules` project token (Infisical `/railway`
`RAILWAY_TOKEN_DATA_SCHEDULES`); the job runs only while the repository variable `CD_DEPLOY` is
`true`. The image build runs the control plane's `--dry-run`, so a broken image fails the deploy.
A cron job has no HTTP endpoint, so the smoke URL only shows that the uptime Worker watching the
`news-capture` heartbeat is up; the job's own health is the heartbeat (alert after 5 h).
Rollback: the command in the failed job's summary (`deploymentRollback`), then revert on `main`.
Turn CD off: `gh variable set CD_DEPLOY -R bookchaowalit/content-news-scraper --body false`.

Bump `DATA_LAKE_PIPELINES_REF` in the Dockerfile when the control plane changes.

Turn it off: remove the cron schedule of `news-capture` in Railway (nothing else runs it).
Undo the data: delete the three news prefixes above from the bucket; no other dataset shares them.
