# syntax=docker/dockerfile:1

FROM docker.io/python:3.13.15-slim-trixie

LABEL name="GramStack" \
      maintainer="Guro Bokum <jiojiajiu@gmail.com>" \
      org.opencontainers.image.source="https://github.com/gurobokum/gramstack" \
      org.opencontainers.image.description="GramStack backend - full-stack starter for Telegram Mini Apps" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    APP_USER=gramstack \
    APP_HOME=/app

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /usr/local/bin/

RUN useradd --create-home $APP_USER

WORKDIR $APP_HOME

COPY --chown=$APP_USER:$APP_USER uv.lock pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

USER $APP_USER
COPY --chown=$APP_USER:$APP_USER . .
RUN python -m scripts.generate_i18n
