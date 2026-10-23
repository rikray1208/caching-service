import logging
from collections import Counter
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from payload_cache.inbound.http.dependencies import get_transformer
from payload_cache.run import create_app
from payload_cache.settings import Settings
from tests.doubles import (
    SpyPoolTransformer,
    SpyTransformer,
    StubCrashError,
    StubCrashingTransformer,
    StubFailingTransformer,
)

SAMPLE_INPUT = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"


def test_sample_is_created_and_read_back_as_the_task_shows(client: TestClient) -> None:
    created = client.post("/payload", json=SAMPLE_INPUT)

    assert created.status_code == 201
    assert created.json()["message"] == "Payload created."

    read = client.get(f"/payload/{created.json()['id']}")

    assert read.status_code == 200
    assert read.json() == {"output": SAMPLE_OUTPUT}


def test_texts_at_the_limits_are_accepted(client: TestClient) -> None:
    longest_text = "\N{GRINNING FACE}" * 1_000  # 1,000 characters, 4,000 bytes in UTF-8
    body = {"list_1": [longest_text, *["a"] * 999], "list_2": [""] * 1_000}

    response = client.post("/payload", json=body)

    assert response.status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"list_1": "a", "list_2": ["b"]}, id="list is a string"),
        pytest.param({"list_1": [1], "list_2": ["b"]}, id="text is a number"),
        pytest.param({"list_1": ["a"]}, id="list missing"),
        pytest.param({"list_1": [], "list_2": []}, id="empty lists"),
        pytest.param({"list_1": ["a"] * 1_001, "list_2": ["b"] * 1_001}, id="1,001 texts"),
        pytest.param({"list_1": ["a" * 1_001], "list_2": ["b"]}, id="1,001 characters"),
        pytest.param({"list_1": ["a\u0000b"], "list_2": ["b"]}, id="NUL character"),
    ],
)
def test_invalid_body_answers_422(client: TestClient, body: dict[str, object]) -> None:
    response = client.post("/payload", json=body)

    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.parametrize(
    ("body", "echoed_input"),
    [
        # Valid JSON, but httpx encodes `json=` as UTF-8, which a lone surrogate is not, so the body goes as bytes.
        pytest.param(b'{"list_1": ["a\\ud800"], "list_2": ["b"]}', "a\ud800", id="lone surrogate"),
        # Not JSON, but Python's parser accepts it.
        pytest.param(b'{"list_1": [NaN], "list_2": ["b"]}', "nan", id="NaN"),
    ],
)
def test_unechoable_input_answers_422_not_500(client: TestClient, body: bytes, echoed_input: str) -> None:
    response = client.post("/payload", content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "list_1", 0]
    assert error["input"] == echoed_input


def test_lists_of_different_lengths_answer_422_with_the_error_body(client: TestClient) -> None:
    response = client.post("/payload", json={"list_1": ["a", "b"], "list_2": ["c"]})

    assert response.status_code == 422
    assert response.json() == {
        "code": "unequal_lists",
        "message": "list_1 and list_2 must have the same length.",
        "details": {"list_1_length": 2, "list_2_length": 1},
    }


def test_unknown_id_answers_404_with_the_error_body(client: TestClient) -> None:
    payload_id = uuid4()

    response = client.get(f"/payload/{payload_id}")

    assert response.status_code == 404
    assert response.json() == {
        "code": "payload_not_found",
        "message": "Payload not found.",
        "details": {"payload_id": str(payload_id)},
    }


def test_malformed_id_answers_422(client: TestClient) -> None:
    response = client.get("/payload/not-a-uuid")

    assert response.status_code == 422


def test_unexpected_error_answers_a_generic_500_and_logs_the_traceback(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    app.dependency_overrides[get_transformer] = lambda: StubCrashingTransformer()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/payload", json=SAMPLE_INPUT)

    assert response.status_code == 500
    assert response.json() == {"code": "internal_server_error", "message": "Internal server error.", "details": None}
    assert StubCrashingTransformer.CRASH_TEXT not in response.text
    [logged_error] = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert logged_error.exc_info is not None
    assert logged_error.exc_info[0] is StubCrashError


def test_a_transformer_failure_answers_503_and_stores_no_payload(
    app: FastAPI, client: TestClient, it_worker_db_engine: Engine
) -> None:
    app.dependency_overrides[get_transformer] = lambda: StubFailingTransformer("second string", "last string")

    response = client.post("/payload", json=SAMPLE_INPUT)

    assert response.status_code == 503
    assert response.json() == {
        "code": "transformer_unavailable",
        "message": "The transformer is unavailable. Try again later.",
        "details": None,
    }
    with it_worker_db_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM payload")).scalar_one() == 0


def test_a_retry_after_a_transformer_failure_calls_only_the_failed_texts(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_transformer] = lambda: StubFailingTransformer("second string", "last string")
    failed = client.post("/payload", json=SAMPLE_INPUT)
    spy = SpyTransformer()
    app.dependency_overrides[get_transformer] = lambda: spy

    retried = client.post("/payload", json=SAMPLE_INPUT)

    assert failed.status_code == 503
    assert retried.status_code == 201
    assert spy.calls == Counter(["second string", "last string"])
    assert client.get(retried.headers["Location"]).json() == {"output": SAMPLE_OUTPUT}


@pytest.fixture
def spy_transformer(app: FastAPI) -> SpyTransformer:
    spy = SpyTransformer()
    app.dependency_overrides[get_transformer] = lambda: spy
    return spy


def test_a_text_repeated_in_a_request_reaches_the_transformer_once(
    client: TestClient, spy_transformer: SpyTransformer
) -> None:
    created = client.post("/payload", json={"list_1": ["x", "x"], "list_2": ["x", "y"]})

    assert spy_transformer.calls == Counter(["x", "y"])
    assert client.get(f"/payload/{created.json()['id']}").json() == {"output": "X, X, X, Y"}


def test_overlapping_inputs_reach_the_transformer_only_for_their_new_texts(
    client: TestClient, spy_transformer: SpyTransformer
) -> None:
    client.post("/payload", json={"list_1": ["a", "b"], "list_2": ["c", "d"]})
    created = client.post("/payload", json={"list_1": ["c", "e"], "list_2": ["a", "f"]})

    assert spy_transformer.calls == Counter(["a", "b", "c", "d", "e", "f"])
    assert client.get(f"/payload/{created.json()['id']}").json() == {"output": "C, A, E, F"}


def test_a_second_app_on_the_same_database_reuses_the_cache(client: TestClient, app_settings: Settings) -> None:
    client.post("/payload", json=SAMPLE_INPUT)
    second_app = create_app(app_settings)
    second_spy = SpyTransformer()
    second_app.dependency_overrides[get_transformer] = lambda: second_spy
    # The same texts as a different input, so that only the transformation cache can answer them.
    swapped_input = {"list_1": SAMPLE_INPUT["list_2"], "list_2": SAMPLE_INPUT["list_1"]}

    with TestClient(second_app) as second_client:
        created = second_client.post("/payload", json=swapped_input)

    assert second_spy.calls == Counter()
    assert client.get(f"/payload/{created.json()['id']}").json() == {
        "output": "OTHER STRING, FIRST STRING, ANOTHER STRING, SECOND STRING, LAST STRING, THIRD STRING"
    }


def test_no_database_connection_is_held_while_the_transformer_runs(app: FastAPI, client: TestClient) -> None:
    transformer = SpyPoolTransformer(app.state["session_factory"].kw["bind"].pool)
    app.dependency_overrides[get_transformer] = lambda: transformer

    client.post("/payload", json=SAMPLE_INPUT)

    assert transformer.checked_out_connections == [0] * 6


def test_an_input_seen_before_answers_200_with_its_id_and_no_transformer_call(
    client: TestClient, spy_transformer: SpyTransformer, it_worker_db_engine: Engine
) -> None:
    created = client.post("/payload", json=SAMPLE_INPUT)
    # Without the stored transformations, only the stored payload can spare the transformer.
    with it_worker_db_engine.begin() as connection:
        connection.execute(text("TRUNCATE transformation"))
    spy_transformer.calls.clear()

    repeated = client.post("/payload", json=SAMPLE_INPUT)

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == {"id": created.json()["id"], "message": "Payload already exists."}
    assert spy_transformer.calls == Counter()


def test_both_answers_locate_the_payload(client: TestClient) -> None:
    created = client.post("/payload", json=SAMPLE_INPUT)
    repeated = client.post("/payload", json=SAMPLE_INPUT)

    payload_path = f"/payload/{created.json()['id']}"
    assert created.headers["Location"] == payload_path
    assert repeated.headers["Location"] == payload_path
    assert client.get(repeated.headers["Location"]).json() == {"output": SAMPLE_OUTPUT}


def test_location_keeps_the_root_path_of_a_proxy(app: FastAPI) -> None:
    with TestClient(app, root_path="/api") as client:
        created = client.post("/payload", json=SAMPLE_INPUT)

    assert created.headers["Location"] == f"/api/payload/{created.json()['id']}"


def test_inputs_with_the_same_output_get_different_ids(client: TestClient) -> None:
    lower = client.post("/payload", json={"list_1": ["a"], "list_2": ["b"]})
    upper = client.post("/payload", json={"list_1": ["A"], "list_2": ["B"]})

    assert upper.status_code == 201
    assert upper.json()["id"] != lower.json()["id"]
    assert client.get(lower.headers["Location"]).json() == {"output": "A, B"}
    assert client.get(upper.headers["Location"]).json() == {"output": "A, B"}
