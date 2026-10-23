FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ARG INSTALL_DEV_DEPENDENCIES="false"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN if [ "$INSTALL_DEV_DEPENDENCIES" = "true" ]; then \
      uv sync --locked --no-cache --dev --no-install-project; \
    else \
      uv sync --locked --no-cache --no-dev --no-install-project; \
    fi

COPY src ./src

RUN if [ "$INSTALL_DEV_DEPENDENCIES" = "true" ]; then \
      uv sync --locked --no-cache --dev --no-editable; \
    else \
      uv sync --locked --no-cache --no-dev --no-editable; \
    fi

COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn payload_cache.run:create_app --factory --host=0.0.0.0 --port=8000"]
