# Hosted news schedule (owner decision D6: Railway cron service `news-capture`, every 2 hours).
# One image holds the data-lake control plane (data-lake-pipelines at a reviewed commit) and this
# collector, laid out the way the control plane finds it under SOLO_BOOK_DEV_ROOT.
# Build from the repository root: railway up (RAILWAY_DOCKERFILE_PATH=deploy/railway-cron/Dockerfile).
FROM python:3.12-slim

# data-lake-pipelines at a reviewed commit; bump deliberately.
ARG DATA_LAKE_PIPELINES_REF=b6e9a1e357000963735ed59518a6caf01b882262

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    SOLO_BOOK_DEV_ROOT=/bookdev PIPELINES_ROOT=/app/data-lake-pipelines

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /app \
 && curl -fsSL "https://codeload.github.com/bookchaowalit/data-lake-pipelines/tar.gz/${DATA_LAKE_PIPELINES_REF}" \
    | tar -xz -C /app \
 && mv "/app/data-lake-pipelines-${DATA_LAKE_PIPELINES_REF}" /app/data-lake-pipelines \
 && cd /app/data-lake-pipelines && uv sync --frozen --no-dev

# The control plane's S3/R2 storage shells out to `aws` (data_lake/storage.py). Its own tool venv
# keeps botocore apart from the control plane's s3fs/aiobotocore pins.
RUN UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install "awscli>=1.36,<2" \
 && aws --version

ARG NEWS_DIR=/bookdev/github/bookchaowalit/public/book-apps/tools/content-news-scraper
COPY pyproject.toml uv.lock ${NEWS_DIR}/
# The collector runs under the control plane's Python, so its locked runtime (+ sentry) goes there too.
RUN cd ${NEWS_DIR} \
 && uv export --frozen --no-dev --extra sentry --no-hashes --no-emit-project -o /tmp/news-requirements.txt \
 && uv pip install --python /app/data-lake-pipelines/.venv/bin/python -r /tmp/news-requirements.txt
COPY news ${NEWS_DIR}/news
COPY news_data ${NEWS_DIR}/news_data
COPY scripts ${NEWS_DIR}/scripts

# Build-time smoke test (the CD gate: a failed build fails the deploy job). The control plane plans
# one cycle without network or writes, so imports, paths and the collector layout are checked here.
RUN cd ${NEWS_DIR} \
 && /app/data-lake-pipelines/.venv/bin/python /app/data-lake-pipelines/infra/scripts/data_lake/run_news_capture.py --dry-run --json \
    | grep -q '"status": "dry-run"' \
 && /app/data-lake-pipelines/.venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); import scheduled_capture"

RUN useradd --create-home --uid 10001 capture && chown -R capture /bookdev
USER capture
WORKDIR ${NEWS_DIR}
CMD ["/app/data-lake-pipelines/.venv/bin/python", "scripts/scheduled_capture.py"]
