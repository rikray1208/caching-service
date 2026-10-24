# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ARG INSTALL_DEV_DEPENDENCIES="false"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# COPY keeps the checkout's modes, which a umask such as 077 leaves unreadable to the user.
# The symbolic a+rX needs Dockerfile 1.14, hence the syntax line.
COPY --chmod=a+rX pyproject.toml uv.lock ./

RUN if [ "$INSTALL_DEV_DEPENDENCIES" = "true" ]; then \
      uv sync --locked --no-cache --dev --no-install-project; \
    else \
      uv sync --locked --no-cache --no-dev --no-install-project; \
    fi

COPY --chmod=a+rX README.md ./
COPY --chmod=a+rX src ./src

RUN if [ "$INSTALL_DEV_DEPENDENCIES" = "true" ]; then \
      uv sync --locked --no-cache --dev --no-editable; \
    else \
      uv sync --locked --no-cache --no-dev --no-editable; \
    fi

COPY --chmod=a+rX alembic.ini ./
COPY --chmod=a+rX migrations ./migrations
COPY --chmod=a+rX tests ./tests

# By id, so that a platform that refuses root, such as Kubernetes with runAsNonRoot, can tell without /etc/passwd.
USER 10001:10001

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.core.run:create_app --factory --host=0.0.0.0 --port=8000"]
