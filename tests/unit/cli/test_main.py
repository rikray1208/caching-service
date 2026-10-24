import codecs
import json
import os
import re
import socket
import sys
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path

import httpx2
import pytest

from app.cli.main import (
    EXIT_INVALID_ARGUMENTS,
    EXIT_OK,
    EXIT_SERVICE_FAILED,
    main,
    read_request_body,
    run,
)
from app.cli.settings import parse_settings
from tests.doubles import FakePayloadApi, payload_client_for

BODY = {"list_1": ["a"], "list_2": ["b"]}
NON_ASCII_BODY = {"list_1": ["café"], "list_2": ["naïve"]}
ROUND_TIME = re.compile(r"Round (\d+) of (\d+): \d+\.\d{3} s")
JSON_LINES = (
    '{"id": "payload-1", "created": true, "output": "A, B"}\n{"id": "payload-1", "created": false, "output": "A, B"}\n'
)
EARLIER_RUN = "a line from an earlier run\n"


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
        pytest.param(["-j", "[1]"], "--json: must be a JSON object", id="json not an object"),
        pytest.param(["-j", "null"], "--json: must be a JSON object", id="json null"),
        pytest.param(["-i", "missing.json"], "--input: Path does not point to a file", id="input missing"),
        pytest.param([], "one of --input and --json is required", id="neither input nor json"),
        pytest.param(["-i", "-", "-j", "{}"], "--input and --json can't both be given", id="both input and json"),
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


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        pytest.param(b"[1]", "must be a JSON object", id="not an object"),
        pytest.param(
            b"{'list_1': []}", "not valid JSON: Expecting property name enclosed in double quotes", id="not JSON"
        ),
        pytest.param(b"\xff{}", "'utf-8' codec can't decode byte 0xff in position 0", id="not UTF-8"),
    ],
)
def test_main_exits_2_when_the_input_file_holds_no_json_object(
    data: bytes, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body_file = tmp_path / "body.json"
    body_file.write_bytes(data)
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-i", str(body_file)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_INVALID_ARGUMENTS
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"cache-cli: error: --input: {reason}")


def test_main_exits_2_when_stdin_holds_no_json_object(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-i", "-"])
    monkeypatch.setattr(sys, "stdin", StringIO('"text"'))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_INVALID_ARGUMENTS
    assert capsys.readouterr() == ("", "cache-cli: error: --input: must be a JSON object\n")


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="the file mode doesn't stop root or Windows")
def test_main_exits_2_when_the_input_file_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body_file = tmp_path / "body.json"
    body_file.write_text("{}")
    body_file.chmod(0)
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-i", str(body_file)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_INVALID_ARGUMENTS
    assert capsys.readouterr() == ("", f"cache-cli: error: --input: [Errno 13] Permission denied: {str(body_file)!r}\n")


@pytest.fixture
def fake_service_for_main(monkeypatch: pytest.MonkeyPatch) -> FakePayloadApi:
    """Has a FakePayloadApi answer the client that main builds, which takes no transport from outside."""
    service = FakePayloadApi()
    client_class = httpx2.Client
    monkeypatch.setattr(
        httpx2, "Client", lambda **kwargs: client_class(transport=httpx2.MockTransport(service), **kwargs)
    )
    return service


@pytest.mark.usefixtures("fake_service_for_main")
def test_main_replaces_the_output_file_with_the_json_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_file = tmp_path / "out.jsonl"
    output_file.write_text(EARLIER_RUN)
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-j", json.dumps(BODY), "-r", "2", "-o", str(output_file)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_OK
    assert output_file.read_text() == JSON_LINES
    out, err = capsys.readouterr()
    assert out == ""
    assert len(err.splitlines()) == 2


@pytest.mark.usefixtures("fake_service_for_main")
def test_main_writes_the_json_lines_to_stdout_for_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-j", json.dumps(BODY), "-r", "2", "-o", "-"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_OK
    assert capsys.readouterr().out == JSON_LINES


def test_main_exits_2_when_the_output_file_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    name_too_long = tmp_path / ("x" * 1000)
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-j", "{}", "-o", str(name_too_long)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_INVALID_ARGUMENTS
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("cache-cli: error: --output: [Errno ")


def test_main_reads_stdin_as_utf_8_whatever_the_locale(
    fake_service_for_main: FakePayloadApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    utf_8_with_bom = codecs.BOM_UTF8 + json.dumps(NON_ASCII_BODY, ensure_ascii=False).encode()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(BytesIO(utf_8_with_bom), encoding="cp1252"))
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-i", "-"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_OK
    assert json.loads(fake_service_for_main.requests[0].content) == NON_ASCII_BODY


def test_main_leaves_the_output_file_alone_when_the_input_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_file = tmp_path / "out.jsonl"
    output_file.write_text(EARLIER_RUN)
    monkeypatch.setattr(sys, "argv", ["cache-cli", "-i", "-", "-o", str(output_file)])
    monkeypatch.setattr(sys, "stdin", StringIO("[1]"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_INVALID_ARGUMENTS
    assert output_file.read_text() == EARLIER_RUN


def test_read_request_body_takes_json_as_given() -> None:
    settings = parse_settings(["-j", json.dumps(BODY)])

    assert read_request_body(settings, StringIO("stdin is not read")) == BODY


@pytest.mark.parametrize("bom", [pytest.param(b"", id="UTF-8"), pytest.param(codecs.BOM_UTF8, id="UTF-8 with a BOM")])
def test_read_request_body_reads_the_input_file(bom: bytes, tmp_path: Path) -> None:
    body_file = tmp_path / "body.json"
    body_file.write_bytes(bom + json.dumps(NON_ASCII_BODY, ensure_ascii=False).encode())
    settings = parse_settings(["-i", str(body_file)])

    assert read_request_body(settings, StringIO("stdin is not read")) == NON_ASCII_BODY


def test_read_request_body_reads_stdin_for_dash() -> None:
    settings = parse_settings(["-i", "-"])

    assert read_request_body(settings, StringIO(json.dumps(BODY))) == BODY


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
