import logging
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from payload_cache.inbound.http.dependencies import get_transformer
from tests.doubles import StubCrashError, StubCrashingTransformer

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
