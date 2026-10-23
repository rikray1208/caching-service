import json
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from payload_cache.cli.client import PayloadClient
from payload_cache.cli.main import EXIT_OK, EXIT_SERVICE_FAILED, run

SAMPLE_INPUT = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"


def test_the_sample_goes_through_the_cli_created_then_reused(client: TestClient) -> None:
    output, progress = StringIO(), StringIO()

    status = run(SAMPLE_INPUT, 2, PayloadClient(client), output=output, progress=progress)

    assert status == EXIT_OK
    first, second = [json.loads(line) for line in output.getvalue().splitlines()]
    assert first == {"id": first["id"], "created": True, "output": SAMPLE_OUTPUT}
    assert second == {"id": first["id"], "created": False, "output": SAMPLE_OUTPUT}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        pytest.param(
            {"list_1": ["a", "b"], "list_2": ["c"]},
            "answered 422 Unprocessable Content: list_1 and list_2 must have the same length.",
            id="the service's error",
        ),
        pytest.param(
            {"list_1": [], "list_2": ["c"]},
            "answered 422 Unprocessable Content: body.list_1: List should have at least 1 item after validation, not 0",
            id="FastAPI's validation error",
        ),
    ],
)
def test_a_body_the_service_rejects_shows_its_422(client: TestClient, body: dict[str, object], message: str) -> None:
    output, progress = StringIO(), StringIO()

    status = run(body, 1, PayloadClient(client), output=output, progress=progress)

    assert status == EXIT_SERVICE_FAILED
    assert output.getvalue() == ""
    assert progress.getvalue() == f"Round 1 of 1 failed: POST http://testserver/payload {message}\n"
