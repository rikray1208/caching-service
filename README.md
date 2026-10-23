# payload-cache

A FastAPI service that generates payloads from two lists of texts.

You need Docker, and [uv](https://docs.astral.sh/uv/) for the commands that run on the host (uv installs Python 3.14 itself).

## Run with Docker

```bash
docker compose up --build
```

Compose starts PostgreSQL 18 and, once its healthcheck passes, the API on <http://localhost:8000>. The API applies the database migrations before it starts. The database credentials in `docker-compose.yml` are for local development only, which is why a fresh clone runs without a `.env`.

`docker compose down` stops both; `docker compose down -v` also deletes the stored data.

## Try the sample

Open Swagger at <http://localhost:8000/docs>.

1. Open `POST /payload`, click **Try it out**: the request body is already the task's sample. Click **Execute**. The answer is `201` with the new payload's id:

   ```json
   {"id": "<payload id>", "message": "Payload created."}
   ```

2. Open `GET /payload/{payload_id}`, click **Try it out**, paste the id and click **Execute**:

   ```json
   {"output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
   ```

The same with `curl`:

```bash
curl -X POST http://localhost:8000/payload \
  -H 'Content-Type: application/json' \
  -d '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
curl http://localhost:8000/payload/<payload id>
```

## Tests

The unit tests run on the host:

```bash
uv run pytest
```

This skips the integration tests, which need PostgreSQL. To run every test, in Docker:

```bash
scripts/start-test-infra.sh
```

The script starts a separate Compose project, `payload-cache-test`, whose services publish no ports, so it never touches the database of `docker compose up`. It runs pytest inside the API image, built with the dev dependencies, on 4 workers, each with its own migrated database. When it ends, passed or failed, it removes the project with its volume. Arguments go to pytest: `scripts/start-test-infra.sh -k api`.

If a run is killed before it cleans up, remove the project by hand:

```bash
docker compose -p payload-cache-test -f docker-compose.yml -f docker-compose.test.yml down -v --remove-orphans
```

The other checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
```

## Migrations

Every schema change is an Alembic revision in `migrations/versions`. To autogenerate one, start the database, which Compose publishes on `127.0.0.1:5433` for this, and point Alembic at it:

```bash
docker compose up -d db
export POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=payload_cache POSTGRES_PASSWORD=payload_cache POSTGRES_DB=payload_cache
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "<what changes>"
```
