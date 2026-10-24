# payload-cache

A FastAPI service that generates payloads from two lists of texts. It stores what the transformer returns for each text in PostgreSQL, so a stored text never reaches the transformer again, across requests and restarts. An input submitted before gets its payload's id back without reaching the transformer at all.

You need Docker, and [uv](https://docs.astral.sh/uv/) for the commands that run on the host (uv installs Python 3.14 itself). The last three sections, [Decisions](#decisions), [Assumptions](#assumptions) and [Shortcuts](#shortcuts), say why it is built this way and what it leaves out.

## Run with Docker

```bash
docker compose up --build
```

Compose starts PostgreSQL 18 and, once its healthcheck passes, the API on <http://localhost:8000>. The API applies the database migrations before it starts. The database credentials in `docker-compose.yml` are for local development only, which is why a fresh clone runs without a `.env`.

The command stays in the foreground with the logs, so run the commands below in a second terminal. Or start it in the background with `docker compose up --build -d`, follow the API's logs with `docker compose logs -f api`, and give the API a few seconds to migrate before the first request.

`docker compose down` removes both containers and keeps the stored data in the `postgres_data` volume for the next `up`. `docker compose down -v` also deletes it, and the next `up` creates the tables again from the migrations.

The image runs the API, the CLI and the tests as an unprivileged user, `app` with id 10001, who can read the code but not change it.

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

## The command-line client

`cache-cli` sends one request body to the service, a POST and then a GET of the payload, and repeats that round `--repeat` times. With the service up from `docker compose up`:

```bash
uv run cache-cli -r 3 -j '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
```

Each round writes one JSON line to stdout, with `created` true when the POST answered `201` and false when it answered `200`. On a database that hasn't seen the sample's texts yet:

```text
{"id": "<payload id>", "created": true, "output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
{"id": "<payload id>", "created": false, "output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
{"id": "<payload id>", "created": false, "output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
```

Each round's time goes to stderr, where the caches show. The first round sends the six texts to the transformer, which Compose holds for 0.5 s per call; the others get the stored payload back:

```text
Round 1 of 3: 0.613 s
Round 2 of 3: 0.010 s
Round 3 of 3: 0.010 s
```

If the sample was posted before, from Swagger above for example, every round prints `created` false and takes milliseconds; if only its texts were, the first round prints `created` true, but takes milliseconds too. `docker compose down -v` and then `docker compose up --build` start again from an empty database.

The body can also come from a file, or from stdin with `-i -`, and the JSON lines can go to a file instead of stdout. The first command writes the task's sample to `sample.json`. The second writes two lines to `out.jsonl`, and the third prints one to stdout; the times go to stderr either way:

```bash
echo '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}' > sample.json
uv run cache-cli -i sample.json -o out.jsonl -r 2
uv run cache-cli -i - < sample.json
```

The API's image has `cache-cli` too, so it also runs without uv on the host. Inside the container, the service is at `localhost:8000`, the default `--host`:

```bash
docker compose exec api cache-cli -r 2 -j '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
docker compose exec -T api cache-cli -i - < sample.json > out.jsonl
```

There, `-i FILE` and `-o FILE` name files inside the container, where the CLI runs as the image's unprivileged user and can't write to its working directory. So the second command reads the body from the host's stdin and writes the JSON lines to a file on the host through a redirect. Its `-T` gives the CLI plain stdin and stdout rather than a terminal, which would change line endings and mix stderr into the file.

The flags:

- `--host URL`, `-h URL`: the service, `http://localhost:8000` by default.
- `--repeat N`, `-r N`: how many rounds, 1 by default.
- `--input FILE`, `-i FILE`: a file that holds the request body, as UTF-8; `-i -` reads it from stdin.
- `--json JSON`, `-j JSON`: the request body itself.
- `--output FILE`, `-o FILE`: the file for the JSON lines, in a directory that must exist. An existing file is replaced, but only once the body is read, so invalid input leaves it as it was. `-o -`, the default, writes them to stdout.
- `--help`: the help, as `uv run cache-cli --help`.

Exactly one of `--input` and `--json` gives the body. `-h` sets the host, as the task's list of arguments has it, so the help is `--help` alone. A flag can't be abbreviated: `--rep 3` is an unknown flag, not `--repeat 3`. Only the flags set these: an exported `HOST`, or any other environment variable, changes nothing.

The CLI checks only that the body is a JSON object and leaves its content to the service, so it can send a body the service rejects, to show the answer. It quotes the service's message:

```bash
uv run cache-cli -j '{"list_1": ["a", "b"], "list_2": ["c"]}'
```

```text
Round 1 of 1 failed: POST http://localhost:8000/payload answered 422 Unprocessable Content: list_1 and list_2 must have the same length.
```

The exit status is 0 when every round succeeds, 1 when the service fails, and 2 for an invalid argument, a body that can't be read or isn't a JSON object, or an output file that can't be opened, with the reason on stderr. The service fails when it can't be reached or answers with an error status. The CLI then stops at that round and doesn't retry, since it is there to show how the service behaves.

## The transformation cache

The transformer, a stand-in for an external service, uppercases a text. What it returns is stored in the `transformation` table, so a text repeated in a request is sent to it once, and a stored text is never sent again, even after a restart or from another instance on the same database. Two requests that arrive together with the same new text both send it, since neither finds it stored yet; the result stored first is kept, and [Concurrent transformer calls](#concurrent-transformer-calls) says what would save the second call. Texts match exactly, with no trimming, case folding or Unicode normalization.

`TRANSFORMER_DELAY` holds each call of the stand-in for that many seconds, as a network call would, so the cache shows in timings. It is 0 by default, and Compose sets it to 0.5: the sample takes about 0.5 s the first time, since its six texts go to the transformer at once, and the same texts again, for example with `list_1` and `list_2` swapped, answer almost at once.

Each request that generates a payload logs one INFO line that says where its texts came from; follow it with `docker compose logs -f api`. An input submitted before logs none, since it transforms nothing. The sample, then the sample with its lists swapped, then `{"list_1": ["x", "x"], "list_2": ["x", "y"]}` log:

```text
api-1  | 2026-10-23 16:56:45,957 INFO payload_cache.application.services.transformation: 6 texts, 6 distinct: 0 from cache, 6 transformed, 0 failed
api-1  | 2026-10-23 16:56:45,990 INFO payload_cache.application.services.transformation: 6 texts, 6 distinct: 6 from cache, 0 transformed, 0 failed
api-1  | 2026-10-23 16:56:47,036 INFO payload_cache.application.services.transformation: 4 texts, 2 distinct: 0 from cache, 2 transformed, 0 failed
```

`distinct` counts a repeated text once, and `from cache`, `transformed` and `failed` always add up to it. With the stand-in, `failed` stays 0: see [When the transformer fails](#when-the-transformer-fails).

## Payload id reuse

`POST /payload` answers `201` with "Payload created." for a new input, and `200` with "Payload already exists." for an input submitted before. Both answers have the same body, `{"id", "message"}`, and set `Location` to the payload's path, `/payload/<payload id>`, relative to the service's URL. An input submitted before gets its old id without a single transformer call.

An input is identified by its fingerprint, the SHA-256 of `[list_1, list_2]` as compact, ASCII-escaped JSON, which is stored with the payload under a unique index. So reuse needs the same texts, in the same order and the same lists: `["a"], ["b"]` and `["A"], ["B"]` get different ids, although both render `"A, B"`.

Two requests that arrive together with the same new input may both generate it, but they get one id: the unique index lets one of them store the payload, and the other answers `200` with that payload's id.

## When the transformer fails

A real transformer is an external service, and some of its failures pass on their own, such as a timeout or a restart. Its adapter raises `TransformerUnavailableError` for those. The request then still sends every other missing text, stores the transformations that succeeded, and answers `503` without storing a payload:

```json
{"code": "transformer_unavailable", "message": "The transformer is unavailable. Try again later.", "details": null}
```

A retry of the same request finds those transformations stored and sends the transformer only the texts that failed. The INFO line counts the failed texts, and a WARNING line with the first failure's traceback follows it. Any other exception from the transformer is a bug: it cancels the calls still running and answers `500`. The uppercase stand-in never fails, so the tests show this with a stub that fails for chosen texts.

The service never retries on its own. The `503` tells the client that a retry may help, and the client decides when to try again. A real transformer adapter would retry transient failures itself, with backoff, for example with tenacity: it knows which failures of its service are transient and how hard that service may be pushed. That keeps one retry layer. Retries in the service on top of the adapter's would multiply the calls to a service that is already failing, and hold the request open meanwhile.

## Concurrent transformer calls

A request sends all its missing texts to the transformer at once, from an AnyIO task group, so it waits about as long as its slowest call. With Compose's `TRANSFORMER_DELAY` of 0.5 s, a POST of 6 texts never sent before took 3.1 s when the calls ran one after another, and 0.5 to 0.6 s with the calls at once (two requests each, timed with `curl`).

A plain task group fails on the first exception, as TypeScript's `Promise.all` rejects on the first rejection, and it also cancels the calls still running, so their results are lost. So each call records a `TransformerUnavailableError` instead of raising it, which makes the group behave like `Promise.allSettled`: a failed call cancels no other, and every success is stored before the `503`. Any other exception is a bug: it cancels the calls still running, and the `500` is logged with an `ExceptionGroup` of the calls that crashed.

The service doesn't limit how many calls run at once, up to 2,000 for the largest request, on the assumption that the transformer sets no concurrency limit. If it had one, its adapter would enforce it, for example with an AnyIO `CapacityLimiter`, as it would handle retries.

Concurrency within a request doesn't help across requests: two requests that arrive together with the same new text both send it. An in-process single-flight would save that call: a `TransformationService` that lives as long as the app and maps each text in flight to an AnyIO event, which a second request waits on instead of calling the transformer. Across instances it would need a claim row in the database. It isn't built, since it saves calls only when requests with the same new text overlap.

## What the API accepts

`list_1` and `list_2` hold 1 to 1,000 texts each, and the same number of texts. A text is up to 1,000 characters long and may be empty. It must not contain `\u0000`, which PostgreSQL text can't store, or a lone surrogate such as `\ud800`, which isn't valid UTF-8. The limits are easier to relax later than to tighten.

Errors answer:

- `422` for a body that breaks these rules. Lists of different lengths answer the service's error body, `{"code": "unequal_lists", "message": …, "details": …}`; the other rules answer FastAPI's `{"detail": [...]}`. A body that isn't valid UTF-8 gets FastAPI's `400` instead. The `{"detail": [...]}` body comes from a handler that replaces FastAPI's own: FastAPI's echoes the input, so a lone surrogate, which UTF-8 can't encode, or a `NaN`, which JSON can't hold, turned its `422` into a `500`. The replacement writes the same body ASCII-escaped, with `NaN` and `Infinity` echoed as the strings `"nan"` and `"inf"`.
- `404` with code `payload_not_found` for an id no payload has, and `422` for a malformed id.
- `503` with code `transformer_unavailable` when the transformer failed for some texts; a retry may succeed.
- `500` with code `internal_server_error` for anything unexpected; the service logs its traceback.

## Tests

The unit tests, in `tests/unit`, cover the rules in `PayloadInput`, the two services and the CLI, with hand-written doubles from `tests/doubles.py` in place of the transformer, the database and the service. The integration tests, in `tests/integration`, run the SQLAlchemy adapters, the HTTP API, and the CLI's rounds against the app, on PostgreSQL. The CLI's test hands its `PayloadClient` FastAPI's `TestClient` as the HTTP client. That is why the CLI uses `httpx2`, not `httpx`: in the locked versions, `TestClient` is an `httpx2.Client`.

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

On GitHub, the workflow in `.github/workflows/ci.yml` runs these three checks and `scripts/start-test-infra.sh` on every push and pull request.

## Migrations

Every schema change is an Alembic revision in `migrations/versions`. To autogenerate one, start the database, which Compose publishes on `127.0.0.1:5433` for this, and point Alembic at it:

```bash
docker compose up -d db
export POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=payload_cache POSTGRES_PASSWORD=payload_cache POSTGRES_DB=payload_cache
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "<what changes>"
```

Nothing is deployed, so a revision may add a NOT NULL column without a backfill, as the payload's fingerprint does. A local database that holds payloads from before that revision fails to migrate: reset it with `docker compose down -v`.

## Decisions

The code is laid out as ports and adapters. `application` holds the rules, in `PayloadInput`, `TransformationService` and `PayloadService`, and the ports they call. `outbound` holds the adapters behind those ports: the stand-in transformer and the SQLAlchemy cache and payload gateway. `inbound/http` holds the routes, the request limits, the table that maps errors to statuses, and the dependencies that build the services and their adapters for each request; `run.py` builds the app with its engine and transformer. So every rule is tested on fakes, and only the adapters, the API and the CLI's test against it need PostgreSQL. `cli` imports none of it: it is a client of the HTTP API like any other.

**POST generates the payload before it answers.** It reuses the id of an input seen before, or takes each transformation from the cache or the transformer, renders the output and stores it. GET is one read by primary key. So both endpoints keep the contract the task's sample shows, and the id that POST returns always belongs to a generated payload. The price is that a POST with new texts waits for the transformer. Two other designs would win under other conditions. Both would reuse the services and adapters, since mainly the moment the texts are transformed moves:

- *Accept now, generate in the background*, with a status that GET reports, a worker, recovery of rows a crash left pending, and clients that poll, once one request's worst case outgrows a client's timeout even with concurrent calls. For example, a transformer that takes 1 s per call and allows 10 calls at once would need 200 s for 2 × 1,000 new texts.
- *Store the input, generate on the first GET*, if payloads are created far more often than they are read and each call costs money. The input would be stored instead of the output, and GET could then fail with `503`, its time depending on the transformer.

**Id reuse means the same input.** The task's "reuse payload identifier for generated payloads already generated before" could also mean any input with the same output: with the uppercase stand-in, `["a"], ["b"]` and `["A"], ["B"]` both give `"A, B"`. This was settled with the employer as the same input only. The other reading would fingerprint the output instead of the input, so `PayloadService` would transform before it looks up; only `PayloadInput` and `PayloadService` would change.

**The unique index, not the lookup, guarantees id reuse.** POST first looks up the input's fingerprint, which saves every transformer call for an input seen before. But two requests with the same new input can both miss that lookup. So the payload is stored with `INSERT … ON CONFLICT (fingerprint) DO NOTHING RETURNING id`. When it returns no row, another request stored the input first, and the same transaction reads that payload's id, which POST returns with `200`.

**Each database operation is its own short transaction.** A POST with new texts makes four: the fingerprint lookup, the cache lookup, the cache save and the payload insert. So no request holds a connection or an open transaction while the transformer runs, and the transformations that succeeded are committed even when the request answers `503`. No rule needs the cache and the payload to commit together: a payload that is never stored is generated again, from the cache, by the next POST of its input. Two details keep this safe under concurrency:

- The payload insert relies on READ COMMITTED: the INSERT waits for a concurrent transaction with the same fingerprint, and the SELECT after it, as a new statement, sees the row that transaction committed. That is PostgreSQL's default, but a server, database or role can set another, so the engine sets it explicitly, and a test checks it under a default of REPEATABLE READ.
- The cache save sorts its rows by key, so two requests that save overlapping texts lock them in the same order and can't deadlock.

**PostgreSQL, though the task allows SQLite.** The transactions would be the same in SQLite: the slow transformer sets them, not the database. But the cache and the id reuse are built to be shared by several workers or instances, and PostgreSQL takes their concurrent writes without SQLite's single-writer lock or a database file that every instance must reach. The price is integration tests that need a running database, which `scripts/start-test-infra.sh` starts in Docker, and a few PostgreSQL specifics, each with a test: `\u0000` is rejected, a text is keyed by its hash since a B-tree entry can't hold 1,000 four-byte characters, and READ COMMITTED is set.

**The output is stored, and the input lists are not.** GET is then a single read that never depends on the transformation cache, and a payload never changes once it is generated. No rule reads the input back, and the fingerprint is enough to recognise it. Generating on GET, or rendering payloads again after the transformer changed, would need the lists stored.

## Assumptions

Where the task leaves a question open, the service follows the assumption below. Each says what a different answer would change.

- **`-h` is listed for both `--host` and `--help`.** It sets the host, as the argument list explains it, and help is `--help` alone. Otherwise `parse_settings` would drop its own parser and let pydantic-settings add `-h/--help`.
- **What `--repeat` repeats, and what goes to `--output`.** The whole round, a POST and a GET with the same body, N times; one JSON line `{"id", "created", "output"}` per round, and each round's time on stderr. Otherwise only `run` in `cli/main.py` would change.
- **Exactly one of `--input` and `--json`, and a file holds one request body**, like the sample. Neither or both is a usage error. Otherwise one validator in `cli/settings.py` would change.
- **The sizes.** 1 to 1,000 texts per list, each up to 1,000 characters, and empty texts allowed. Otherwise the constants in `inbound/http/schemas.py` would change. Past about 10,900 new texts per request, the cache's `save` would also need batching, since it binds three parameters per text and asyncpg takes at most 32,767 per statement.
- **The transformer is deterministic, and its results can be kept forever.** Otherwise `TransformationCache.find` would check an age, from the `created_at` that each transformation already stores, or the table would get a version column.
- **The output stays one string joined with `", "`**, as in the sample, although a text that contains `", "` makes it ambiguous. Otherwise `render` and `PayloadResponse` would change, for example to a list.
- **The real transformer takes one text per call, may fail for a while, and has no rate or concurrency limit.** A batch API would change the `Transformer` port and `TransformationService`. A limit would go into its adapter, for example as an AnyIO `CapacityLimiter`.
- **POST answers `201` for a new payload and `200` for an input seen before**, with the same body. Otherwise the route's statuses would change, and with them the CLI's `created`, which it reads from the status.
- **A "payload file" is the generated output, stored as a row**, and GET answers it as JSON, as in the sample output. A download would make `get_payload` answer `text/plain` with `Content-Disposition: attachment`; the storage would stay.
- **The CLI's "sanitizing" covers its arguments**, and checks only that the body is a JSON object, so it can send bodies the service rejects. Otherwise a model of the body in `cli/` would check the lists where the body is read, and the CLI could no longer show the service's `422`s.

## Shortcuts

- **The transformer is a stand-in** that uppercases each text, held by `TRANSFORMER_DELAY` to act like a network call. A real one would be another adapter of the `Transformer` port, owning its HTTP client, its retries and any limit on concurrent calls.
- **The database credentials are dev-only values in `docker-compose.yml`**, so that a fresh clone runs without a `.env`. The service reads them from the `POSTGRES_*` variables, which a deployment would set from its secrets.
- **The service never retries** a transformer call: see [When the transformer fails](#when-the-transformer-fails).
- **Two concurrent requests with the same new text both call the transformer**, and the single-flight that would save the second call isn't built: see [Concurrent transformer calls](#concurrent-transformer-calls).
- **Transformations never expire**, which the determinism assumption allows.
- **No limit on concurrent transformer calls**: a request with 2,000 new texts makes 2,000 calls at once.
- **No cap on the request body's size.** The limits are checked once the whole body is parsed, and a `422` echoes the input it rejects.
- **The CLI waits 5 s per network operation**, httpx2's default. A POST that takes longer reports `got no answer: timed out` and exits 1, though the service may still store the payload.
- **The API has no healthcheck**, so `docker compose up -d` returns while it still migrates: a request in the next second or two is refused.
- **The database logs every write statement** (`log_statement=mod`), so the clients' texts and outputs end up in its log too.
