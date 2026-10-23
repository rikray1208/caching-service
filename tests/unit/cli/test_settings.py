import pytest
from pydantic import HttpUrl, ValidationError

from payload_cache.cli.settings import parse_request_body, parse_settings

BODY = '{"list_1": ["a"], "list_2": ["b"]}'


def test_defaults_need_only_the_body() -> None:
    settings = parse_settings(["--json", BODY])

    assert settings.host == HttpUrl("http://localhost:8000")
    assert settings.repeat == 1
    assert settings.json_text == BODY


@pytest.mark.parametrize("flag", ["--repeat", "-r"])
def test_repeat_sets_the_number_of_rounds(flag: str) -> None:
    assert parse_settings(["-j", BODY, flag, "3"]).repeat == 3


@pytest.mark.parametrize("flag", ["--json", "-j"])
def test_json_sets_the_body_as_given(flag: str) -> None:
    assert parse_settings([flag, BODY]).json_text == BODY


def test_host_sets_the_service_url() -> None:
    settings = parse_settings(["-j", BODY, "--host", "https://cache.example:9000/api"])

    assert settings.host == HttpUrl("https://cache.example:9000/api")


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
    ],
)
def test_json_that_is_not_a_json_object_is_rejected(json_text: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings(["-j", json_text])

    assert [error["loc"] for error in exc_info.value.errors()] == [("json",)]


def test_json_content_is_left_to_the_service() -> None:
    lists_of_different_lengths = '{"list_1": ["a", "b"], "list_2": ["c"]}'

    assert parse_settings(["-j", lists_of_different_lengths]).json_text == lists_of_different_lengths


def test_missing_json_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_settings([])

    assert [(error["loc"], error["type"]) for error in exc_info.value.errors()] == [(("json",), "missing")]


def test_unknown_flag_exits_with_status_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_settings(["-j", BODY, "--hots", "http://localhost:8000"])

    assert exc_info.value.code == 2


def test_exported_variables_set_no_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "http://elsewhere.example:9000")
    monkeypatch.setenv("REPEAT", "5")
    monkeypatch.setenv("R", "5")

    settings = parse_settings(["-j", BODY])

    assert settings.host == HttpUrl("http://localhost:8000")
    assert settings.repeat == 1


def test_an_exported_json_is_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JSON", BODY)
    monkeypatch.setenv("J", BODY)

    with pytest.raises(ValidationError):
        parse_settings([])


def test_parse_request_body_returns_the_object() -> None:
    assert parse_request_body(BODY) == {"list_1": ["a"], "list_2": ["b"]}
