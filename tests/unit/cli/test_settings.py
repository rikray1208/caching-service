import re
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from payload_cache.cli.settings import CliSettings, parse_request_body, parse_settings

BODY = '{"list_1": ["a"], "list_2": ["b"]}'


def test_defaults_need_only_the_body() -> None:
    settings = parse_settings(["--json", BODY])

    assert settings.host == HttpUrl("http://localhost:8000")
    assert settings.repeat == 1
    assert settings.json_text == BODY
    assert settings.input_path is None
    assert settings.output_path == "-"


@pytest.mark.parametrize("flag", ["--repeat", "-r"])
def test_repeat_sets_the_number_of_rounds(flag: str) -> None:
    assert parse_settings(["-j", BODY, flag, "3"]).repeat == 3


@pytest.mark.parametrize("flag", ["--json", "-j"])
def test_json_sets_the_body_as_given(flag: str) -> None:
    assert parse_settings([flag, BODY]).json_text == BODY


@pytest.mark.parametrize("flag", ["--input", "-i"])
def test_input_names_the_body_file_without_reading_it(flag: str, tmp_path: Path) -> None:
    body_file = tmp_path / "body.json"
    body_file.write_text("not read while the arguments are parsed")

    settings = parse_settings([flag, str(body_file)])

    assert settings.input_path == body_file
    assert settings.json_text is None


def test_input_dash_is_stdin() -> None:
    assert parse_settings(["-i", "-"]).input_path == "-"


@pytest.mark.parametrize("name", [pytest.param("missing.json", id="missing"), pytest.param(".", id="a directory")])
def test_input_that_is_not_a_file_is_rejected(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(["-i", str(tmp_path / name)])

    assert [(error["loc"][0], error["type"]) for error in exc_info.value.errors()] == [("input", "path_not_file")]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        pytest.param([], "Value error, one of --input and --json is required", id="neither"),
        pytest.param(["-i", "-", "-j", BODY], "Value error, --input and --json can't both be given", id="both"),
    ],
)
def test_exactly_one_of_input_and_json_is_required(args: list[str], message: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(args)

    assert [(error["loc"], error["msg"]) for error in exc_info.value.errors()] == [((), message)]


@pytest.mark.parametrize(
    "args", [pytest.param(["-j", "null"], id="alone"), pytest.param(["-i", "-", "-j", "null"], id="with --input")]
)
def test_json_null_is_no_json_object_rather_than_no_json(args: list[str]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(args)

    assert [(error["loc"], error["msg"]) for error in exc_info.value.errors()] == [
        (("json",), "Value error, must be a JSON object")
    ]


def test_null_names_a_file_called_null(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("null").write_text(BODY)

    assert parse_settings(["-i", "null"]).input_path == Path("null")
    assert parse_settings(["-j", BODY, "-o", "null"]).output_path == Path("null")


@pytest.mark.parametrize("flag", ["--output", "-o"])
def test_output_names_the_file_for_the_json_lines(flag: str, tmp_path: Path) -> None:
    output_file = tmp_path / "out.jsonl"

    assert parse_settings(["-j", BODY, flag, str(output_file)]).output_path == output_file
    assert not output_file.exists()


def test_output_dash_is_stdout() -> None:
    assert parse_settings(["-j", BODY, "-o", "-"]).output_path == "-"


def test_output_in_a_missing_directory_is_rejected(tmp_path: Path) -> None:
    missing_directory = tmp_path / "missing"

    with pytest.raises(ValidationError) as exc_info:
        parse_settings(["-j", BODY, "-o", str(missing_directory / "out.jsonl")])

    assert [(error["loc"][0], error["msg"]) for error in exc_info.value.errors()] == [
        ("output", f"Value error, {missing_directory} is not a directory")
    ]


def test_output_that_is_a_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(["-j", BODY, "-o", str(tmp_path)])

    assert [(error["loc"][0], error["msg"]) for error in exc_info.value.errors()] == [
        ("output", f"Value error, {tmp_path} is a directory")
    ]


@pytest.mark.parametrize("flag", ["--host", "-h"])
def test_host_sets_the_service_url(flag: str) -> None:
    settings = parse_settings(["-j", BODY, flag, "https://cache.example:9000/api"])

    assert settings.host == HttpUrl("https://cache.example:9000/api")


def test_h_is_never_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_settings(["-j", BODY, "-h"])

    assert exc_info.value.code == 2


def test_help_names_cache_cli_and_lists_h_for_the_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("PYTHON_COLORS", "0")

    with pytest.raises(SystemExit) as exc_info:
        parse_settings(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert help_text.startswith("usage: cache-cli [--help] [--host URL] [--repeat N] ")
    assert str(CliSettings.__doc__) in " ".join(help_text.split())
    assert re.search(r"^  --help +show this help message and exit$", help_text, re.MULTILINE)
    assert re.search(
        r"^  --host, -h URL +the caching service, http://localhost:8000 by default$", help_text, re.MULTILINE
    )


@pytest.mark.parametrize(
    ("args", "flag"),
    [
        pytest.param(["--host", "localhost:8000"], "host", id="host without a scheme"),
        pytest.param(["--host", "ftp://cache.example"], "host", id="host not http"),
        pytest.param(["--host", "http://localhost:8000?x=1"], "host", id="host with a query"),
        pytest.param(["--host", "http://localhost:8000#top"], "host", id="host with a fragment"),
        pytest.param(["-r", "0"], "repeat", id="repeat 0"),
        pytest.param(["-r", "-1"], "repeat", id="repeat negative"),
        pytest.param(["-r", "two"], "repeat", id="repeat not a number"),
        pytest.param(["-r", "1.5"], "repeat", id="repeat not an integer"),
    ],
)
def test_invalid_value_is_rejected(args: list[str], flag: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(["-j", BODY, *args])

    assert [error["loc"] for error in exc_info.value.errors()] == [(flag,)]


@pytest.mark.parametrize(
    "json_text",
    [
        pytest.param("[1]", id="array"),
        pytest.param('"text"', id="string"),
        pytest.param("null", id="null"),
        pytest.param("{'list_1': []}", id="not JSON"),
        pytest.param("", id="empty"),
        pytest.param('{"a": ' + "[" * 1_000_000, id="nested too deeply"),
    ],
)
def test_json_that_is_not_a_json_object_is_rejected(json_text: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(["-j", json_text])

    assert [error["loc"] for error in exc_info.value.errors()] == [("json",)]


def test_json_content_is_left_to_the_service() -> None:
    lists_of_different_lengths = '{"list_1": ["a", "b"], "list_2": ["c"]}'

    assert parse_settings(["-j", lists_of_different_lengths]).json_text == lists_of_different_lengths


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["--hots", "http://localhost:8000"], id="unknown"),
        pytest.param(["--rep", "3"], id="abbreviated"),
        pytest.param(["--hel"], id="abbreviated help"),
    ],
)
def test_unknown_or_abbreviated_flag_exits_with_status_2(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_settings(["-j", BODY, *args])

    assert exc_info.value.code == 2


def test_exported_variables_set_no_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "http://elsewhere.example:9000")
    monkeypatch.setenv("H", "http://elsewhere.example:9000")
    monkeypatch.setenv("REPEAT", "5")
    monkeypatch.setenv("R", "5")
    monkeypatch.setenv("INPUT", "-")
    monkeypatch.setenv("I", "-")
    monkeypatch.setenv("OUTPUT", "out.jsonl")
    monkeypatch.setenv("O", "out.jsonl")

    settings = parse_settings(["-j", BODY])

    assert settings.host == HttpUrl("http://localhost:8000")
    assert settings.repeat == 1
    assert settings.input_path is None
    assert settings.output_path == "-"


def test_an_exported_json_is_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JSON", BODY)
    monkeypatch.setenv("J", BODY)

    with pytest.raises(ValidationError):
        parse_settings([])


def test_parse_request_body_returns_the_object() -> None:
    assert parse_request_body(BODY) == {"list_1": ["a"], "list_2": ["b"]}
