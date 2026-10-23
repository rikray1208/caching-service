import json
import re
import socket
import sys
from io import StringIO

import httpx2
import pytest

from payload_cache.cli.main import EXIT_INVALID_ARGUMENTS, EXIT_OK, EXIT_SERVICE_FAILED, main, run
from tests.doubles import FakePayloadApi, payload_client_for

BODY = {"list_1": ["a"], "list_2": ["b"]}
ROUND_TIME = re.compile(r"Round (\d+) of (\d+): \d+\.\d{3} s")


def test_each_round_posts_and_gets_the_body_and_writes_a_json_line() -> None:
    service = FakePayloadApi()
    output, progress = StringIO(), StringIO()

    status = run(BODY, 3, payload_client_for(service), output=output, progress=progress)

    assert status == EXIT_OK
    assert [json.loads(line) for line in output.getvalue().splitlines()] == [
        {"id": "payload-1", "created": True, "output": "A, B"},
        {"id": "payload-1", "created": False, "output": "A, B"},
        {"id": "payload-1", "created": False, "output": "A, B"},
    ]
    assert [(request.method, request.url.path) for request in service.requests] == [
        ("POST", "/payload"),
        ("GET", "/payload/payload-1"),
    ] * 3
    assert len({request.content for request in service.requests if request.method == "POST"}) == 1
    rounds = [ROUND_TIME.fullmatch(line) for line in progress.getvalue().splitlines()]
    assert [match.groups() if match else None for match in rounds] == [("1", "3"), ("2", "3"), ("3", "3")]


def test_an_error_status_ends_the_run_at_its_round_without_a_retry() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx2.Response(200, json={"output": "A, B"})
        if len(requests) == 1:
            return httpx2.Response(201, json={"id": "payload-1", "message": "Payload created."})
        error = {"code": "transformer_unavailable", "message": "The transformer is unavailable.", "details": None}
        return httpx2.Response(503, json=error)

    output, progress = StringIO(), StringIO()

    status = run(BODY, 3, payload_client_for(handler), output=output, progress=progress)

    assert status == EXIT_SERVICE_FAILED
    assert len(output.getvalue().splitlines()) == 1
    assert [request.method for request in requests] == ["POST", "GET", "POST"]
    assert progress.getvalue().splitlines()[-1] == (
        "Round 2 of 3 failed: POST http://service.test/payload answered 503 Service Unavailable: "
        "The transformer is unavailable."
    )


def test_a_network_error_ends_the_run_with_exit_1() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("All connection attempts failed")

    output, progress = StringIO(), StringIO()

    status = run(BODY, 2, payload_client_for(handler), output=output, progress=progress)

    assert status == EXIT_SERVICE_FAILED
    assert output.getvalue() == ""
    assert progress.getvalue() == (
        "Round 1 of 2 failed: POST http://service.test/payload got no answer: All connection attempts failed\n"
    )


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        pytest.param(["-j", "[1]"], "--json: Value error, must be a JSON object", id="json not an object"),
        pytest.param([], "--json: Field required", id="json missing"),
        pytest.param(["-j", "{}", "-r", "0"], "--repeat: Input should be greater than 0", id="repeat 0"),
        pytest.param(
            ["-j", "{}", "--host", "localhost:8000"],
            "--host: URL scheme should be 'http' or 'https'",
            id="host without a scheme",
        ),
    ],
)
def test_main_exits_2_with_the_reason_for_an_invalid_argument(
    args: list[str], reason: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["cache-cli", *args])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_INVALID_ARGUMENTS
    assert capsys.readouterr() == ("", f"cache-cli: error: {reason}\n")


def test_main_exits_1_when_the_service_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with socket.socket() as probe:  # a port that was free a moment ago, so nothing listens on it
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(sys, "argv", ["cache-cli", "--host", f"http://127.0.0.1:{port}", "-j", "{}"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_SERVICE_FAILED
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"Round 1 of 1 failed: POST http://127.0.0.1:{port}/payload got no answer: ")
