# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

FROM ghcr.io/astral-sh/uv:0.8.11@sha256:8101ad825250a114e7bef89eefaa73c31e34e10ffbe5aff01562740bac97553c AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    RULER_WORKSPACE_ROOT=/app \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp/ruler
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install --no-install-recommends -y \
    ca-certificates swi-prolog-nox libglib2.0-0 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 ruler && useradd --uid 10001 --gid ruler --no-create-home ruler
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
# The build context is allowlisted. CI supplies reviewed repository inputs and
# prepared evidence for the initial workspace.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable \
    && mkdir -p /tmp/ruler && chown -R 10001:10001 /tmp/ruler
ENV UV_CACHE_DIR=/tmp/ruler/.cache/uv
USER 10001:10001
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "ruler", "serve", "mcp", "--transport", "streamable-http", "--host", "0.0.0.0"]
