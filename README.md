# payload-cache

A FastAPI service that builds a payload from two lists of texts: each text goes through a transformer, a stand-in for an external service, and the results are interleaved. Transformations are cached, so a text reaches the transformer once, across requests and restarts, and an input posted before gets its payload id back without any transformer call.

POST generates the payload before it answers, and GET only reads the stored output by id. This way every id that POST returns points to a finished payload, as the task's sample implies. The cost is that a POST with new texts has to wait for the transformer. If that wait ever grew longer than a client's timeout, the work would move to a background worker, and clients would poll until their payload is ready.

To find an input posted before, POST looks up a SHA-256 fingerprint of both lists. Only exactly the same lists match, not different texts with the same output, as agreed with the employer. The fingerprint has a unique index, and that index, not the lookup, guarantees one id per input. Two requests with the same new input can both miss the lookup, but only one of them can insert the payload, and the other answers with that payload's id.

The texts missing from the cache go to the transformer all at once, so a request waits about as long as its slowest call. With Compose's delay of 0.5 s per call, six new texts took 3.1 s when sent one by one, and about half a second when sent together. When some calls fail, the others still finish, and their results are stored before the request answers `503`. A retry of that request then sends the transformer only the texts that failed. The service doesn't retry on its own. A real transformer's adapter would, since it knows which errors of its service are temporary and how hard the service can be pushed.

Each database operation is its own short transaction, so no request holds a database connection while it waits for the transformer. The data lives in PostgreSQL rather than SQLite, which the task also allows, because several instances of the service are meant to share the cache and write to it at once. SQLite lets only one of them write at a time, and they would all need to reach the same database file.

You need Docker, and [uv](https://docs.astral.sh/uv/) for the commands on the host.

## Quickstart

```bash
docker compose up --build -d --wait
```

This starts PostgreSQL 18 and the API on <http://localhost:8000>, which applies the migrations first; `--wait` returns once its `GET /health` answers. `docker compose down` keeps the data, and `down -v` deletes it.

Swagger is at <http://localhost:8000/docs>, with the task's sample as the example body. With curl:

```bash
curl -i -X POST http://localhost:8000/payload \
  -H 'Content-Type: application/json' \
  -d '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
curl http://localhost:8000/payload/<payload id>
```

The POST answers `201`, `Location: /payload/<payload id>` and `{"id": "<payload id>", "message": "Payload created."}`; the same POST again answers `200` with the same id and "Payload already exists.". The GET answers:

```json
{"output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
```

`docker compose logs -f api` shows where each generated payload's texts came from:

```text
api-1  | 2026-10-23 16:56:45,957 INFO app.payload.application.services.transformation: 6 texts, 6 distinct: 0 from cache, 6 transformed, 0 failed
```

## API

Each list holds 1 to 1,000 texts, both the same number. A text has at most 1,000 characters, may be empty, and must not contain `\u0000` (PostgreSQL can't store it) or a lone surrogate (not valid UTF-8).

| Status | When |
|---|---|
| `201` / `200` | `POST /payload` with a new input / one posted before. Same body and `Location`. |
| `404` | `payload_not_found`: no payload has that id. |
| `422` | A malformed id or a body that breaks the rules above: `unequal_lists`, or FastAPI's `{"detail": [...]}`. |
| `400` | A body that isn't valid UTF-8. |
| `503` | `transformer_unavailable`: the transformer failed for some texts; a retry may succeed. |
| `500` | `internal_server_error`, with the traceback logged. |

The service's errors answer `{"code", "message", "details"}`. `GET /health` answers `200`, or `503` when the database doesn't answer `SELECT 1` within a second.

## CLI

```bash
uv run cache-cli -r 3 -j '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
```

Each round is a POST and a GET. It writes one JSON line, `{"id", "created", "output"}`, with `created` true for a `201`, and its time to stderr. On an empty database, round 1 takes about 0.6 s, since Compose's `TRANSFORMER_DELAY` holds each transformer call for 0.5 s, and the later rounds about 0.01 s. After the Quickstart's POST, every round takes milliseconds.

| Flag | Meaning | Default |
|---|---|---|
| `-h`, `--host URL` | The service. | `http://localhost:8000` |
| `-r`, `--repeat N` | How many rounds. | `1` |
| `-i`, `--input FILE` | A UTF-8 file with the request body; `-` is stdin. | |
| `-j`, `--json JSON` | The request body itself. | |
| `-o`, `--output FILE` | Where the JSON lines go; `-` is stdout. | `-` |
| `--help` | The help. | |

Exactly one of `-i` and `-j`. The CLI only checks that the body is a JSON object, so it can show the service's `422`s. It exits 0 when every round succeeds, 1 at the first round the service fails, and 2 for invalid arguments, input or output file.

The image has the CLI too: `docker compose exec api cache-cli -j '{"list_1": ["a"], "list_2": ["b"]}'`.

## Tests

```bash
uv run pytest
scripts/start-test-infra.sh
uv run ruff format --check . && uv run ruff check . && uv run mypy
```

`uv run pytest` runs the unit tests: the rules, the services and the CLI, on the doubles in `tests/doubles.py`. The integration tests, which run the SQLAlchemy adapters, the API and the CLI against PostgreSQL, skip there. `scripts/start-test-infra.sh` runs every test in a throwaway Compose project, `payload-cache-test`; its arguments go to pytest. CI runs the checks and the script on every push and pull request.

The CLI uses `httpx2`, not `httpx`, because its integration test passes it FastAPI's `TestClient`, which is an `httpx2.Client` in the locked versions.

## Migrations

Schema changes are Alembic revisions in `migrations/versions`. To autogenerate one against the database Compose publishes on `127.0.0.1:5433`:

```bash
docker compose up -d db
export POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=payload_cache POSTGRES_PASSWORD=payload_cache POSTGRES_DB=payload_cache
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "<what changes>"
```
