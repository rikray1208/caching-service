# payload-cache

A FastAPI service that generates payloads from two lists of texts. It stores what the transformer returns for each text in PostgreSQL, so a stored text never reaches the transformer again, across requests and restarts. An input submitted before gets its payload's id back without reaching the transformer at all.

You need Docker, and [uv](https://docs.astral.sh/uv/) for the commands that run on the host (uv installs Python 3.14 itself).

## Run with Docker

```bash
docker compose up --build
```

Compose starts PostgreSQL 18 and, once its healthcheck passes, the API on <http://localhost:8000>. The API applies the database migrations before it starts. The database credentials in `docker-compose.yml` are for local development only, which is why a fresh clone runs without a `.env`.

`docker compose down` stops both; `docker compose down -v` also deletes the stored data.

## Try the sample

Open Swagger at <http://localhost:8000/docs>.

1. Open `POST /payload`, click **Try it out**: the request body is already the task's sample. Click **Execute**. The answer is `201` with the new payload's id, and its `Location` header is the payload's path, `/payload/<payload id>`:

   ```json
   {"id": "<payload id>", "message": "Payload created."}
   ```

2. Open `GET /payload/{payload_id}`, click **Try it out**, paste the id and click **Execute**:

   ```json
   {"output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
   ```

3. Click **Execute** on `POST /payload` again. The same input answers `200` with the same id and the same `Location`:

   ```json
   {"id": "<payload id>", "message": "Payload already exists."}
   ```

The same with `curl`, where `-i` shows the status and `Location`:

```bash
curl -i -X POST http://localhost:8000/payload \
  -H 'Content-Type: application/json' \
  -d '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
curl http://localhost:8000/payload/<payload id>
```

## The transformation cache

The transformer, a stand-in for an external service, uppercases a text. What it returns is stored in the `transformation` table, so a text repeated in a request is sent to it once, and a stored text is never sent again, even after a restart or from another instance on the same database. Two requests that arrive together with the same new text both send it, since neither finds it stored yet; the result stored first is kept. Texts match exactly, with no trimming, case folding or Unicode normalization.

`TRANSFORMER_DELAY` holds each call of the stand-in for that many seconds, as a network call would, so the cache shows in timings. It is 0 by default, and Compose sets it to 0.5: the sample takes about 3 s the first time, and the same texts again, for example with `list_1` and `list_2` swapped, answer almost at once.

Each request that generates a payload logs one INFO line that says where its texts came from; follow it with `docker compose logs -f api`. An input submitted before logs none, since it transforms nothing. The sample, then the sample with its lists swapped, then `{"list_1": ["x", "x"], "list_2": ["x", "y"]}` log:

```text
api-1  | 2026-10-23 16:05:43,061 INFO payload_cache.application.services.transformation: 6 texts, 6 distinct: 0 from cache, 6 transformed
api-1  | 2026-10-23 16:05:43,102 INFO payload_cache.application.services.transformation: 6 texts, 6 distinct: 6 from cache, 0 transformed
api-1  | 2026-10-23 16:05:44,140 INFO payload_cache.application.services.transformation: 4 texts, 2 distinct: 0 from cache, 2 transformed
```

`distinct` counts a repeated text once, and `from cache` plus `transformed` always add up to it.

## Payload id reuse

`POST /payload` answers `201` with "Payload created." for a new input, and `200` with "Payload already exists." for an input submitted before. Both answers have the same body, `{"id", "message"}`, and set `Location` to the payload's path, `/payload/<payload id>`, relative to the service's URL. An input submitted before gets its old id without a single transformer call.

An input is identified by its fingerprint, the SHA-256 of `[list_1, list_2]` as compact, ASCII-escaped JSON, which is stored with the payload under a unique index. So reuse needs the same texts, in the same order and the same lists: `["a"], ["b"]` and `["A"], ["B"]` get different ids, although both render `"A, B"`.

Two requests that arrive together with the same new input may both generate it, but they get one id: the unique index lets one of them store the payload, and the other answers `200` with that payload's id.

## What the API accepts

`list_1` and `list_2` hold 1 to 1,000 texts each, and the same number of texts. A text is up to 1,000 characters long and may be empty. It must not contain `\u0000`, which PostgreSQL text can't store, or a lone surrogate such as `\ud800`, which isn't valid UTF-8. The limits are easier to relax later than to tighten.

Errors answer:

- `422` for a body that breaks these rules. Lists of different lengths answer the service's error body, `{"code": "unequal_lists", "message": …, "details": …}`; the other rules answer FastAPI's `{"detail": [...]}`. A body that isn't valid UTF-8 gets FastAPI's `400` instead.
- `404` with code `payload_not_found` for an id no payload has, and `422` for a malformed id.
- `500` with code `internal_server_error` for anything unexpected; the service logs its traceback.

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

Nothing is deployed, so a revision may add a NOT NULL column without a backfill, as the payload's fingerprint does. A local database that holds payloads from before that revision fails to migrate: reset it with `docker compose down -v`.
