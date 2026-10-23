#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT_NAME="payload-cache-test"
COMPOSE_FILE="docker-compose.yml"
TEST_COMPOSE_FILE="docker-compose.test.yml"
PYTEST_WORKERS=4

DOCKER_COMPOSE_TEST=(
    docker compose
    -p "$PROJECT_NAME"
    -f "$COMPOSE_FILE"
    -f "$TEST_COMPOSE_FILE"
)

cleanup() {
    "${DOCKER_COMPOSE_TEST[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup

"${DOCKER_COMPOSE_TEST[@]}" up -d --build --wait --wait-timeout 180 db

"${DOCKER_COMPOSE_TEST[@]}" run --rm --build -e IT_TEST_INFRA=1 api \
    pytest -v -ra -n "$PYTEST_WORKERS" "$@"
