# syntax=docker/dockerfile:1.7
# CloudBox Support API — multi-stage build with uv; runtime runs as a non-root user and works with a
# read-only root filesystem (Azure Container Apps / docker compose `read_only: true`).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ------------------------------------------------------------------ build
FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first (cached layer), then the project itself (non-editable install into the venv).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY backend ./backend
# --reinstall-package: never reuse a cached wheel of this project (its source changed even if its version
# did not); together with [tool.uv] cache-keys this guarantees the image contains the current code.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --reinstall-package cloudbox-support-agent

# ------------------------------------------------------------------ runtime
FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
# Knowledge-base sources, seed data and web fixtures are versioned with the code (docs-as-code).
COPY --chown=root:root data /app/data

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_JSON=true \
    DATA_DIR=/app/data

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "backend.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-graceful-shutdown", "30"]
