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

## The command-line client

`cache-cli` sends one request body to the service, a POST and then a GET of the payload, and repeats that round `--repeat` times. With the service up from `docker compose up`:

```bash
uv run cache-cli -r 3 -j '{"list_1": ["first string", "second string", "third string"], "list_2": ["other string", "another string", "last string"]}'
```

Each round writes one JSON line to stdout, with `created` true when the POST answered `201` and false when it answered `200`:

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

The body can also come from a file, or from stdin with `-i -`, and the JSON lines can go to a file instead of stdout. With the task's sample in `sample.json`, the first command writes two lines to `out.jsonl`, and the second prints one to stdout; the times go to stderr either way:

```bash
uv run cache-cli -i sample.json -o out.jsonl -r 2
uv run cache-cli -i - < sample.json
```

The flags:

- `--host URL`, `-h URL`: the service, `http://localhost:8000` by default.
- `--repeat N`, `-r N`: how many rounds, 1 by default.
- `--input FILE`, `-i FILE`: a file that holds the request body, as UTF-8; `-i -` reads it from stdin.
- `--json JSON`, `-j JSON`: the request body itself.
- `--output FILE`, `-o FILE`: the file for the JSON lines, in a directory that must exist. An existing file is replaced, but only once the body is read, so invalid input leaves it as it was. `-o -`, the default, writes them to stdout.
- `--help`: the help.

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

- `422` for a body that breaks these rules. Lists of different lengths answer the service's error body, `{"code": "unequal_lists", "message": …, "details": …}`; the other rules answer FastAPI's `{"detail": [...]}`. A body that isn't valid UTF-8 gets FastAPI's `400` instead.
- `404` with code `payload_not_found` for an id no payload has, and `422` for a malformed id.
- `503` with code `transformer_unavailable` when the transformer failed for some texts; a retry may succeed.
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
