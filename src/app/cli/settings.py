import json
from argparse import Action, ArgumentParser
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    AfterValidator,
    AliasChoices,
    Discriminator,
    Field,
    FilePath,
    HttpUrl,
    PositiveInt,
    Tag,
    model_validator,
)
from pydantic_settings import BaseSettings, CliApp, CliSettingsSource, PydanticBaseSettingsSource

PROG_NAME: Final = "cache-cli"
_DEFAULT_HOST: Final = "http://localhost:8000"
_DEFAULT_REPEAT: Final = 1
# Each value named and each flag described as in the spec's argument list. pydantic-settings would name a value after
# its type, such as HttpUrl, and give the argument it reads as None as the default of --input and --json.
_ARGUMENT_HELP: Final = {
    "host": {"metavar": "URL", "help": f"the caching service, {_DEFAULT_HOST} by default"},
    "repeat": {"metavar": "N", "help": f"how many rounds of POST and GET to send, {_DEFAULT_REPEAT} by default"},
    "input": {"metavar": "FILE|-", "help": "a file that holds the request body, or - for stdin; give this or --json"},
    "json": {"metavar": "JSON", "help": "the request body, a JSON object; give this or --input"},
    "output": {"metavar": "FILE|-", "help": "the file for the JSON lines, or - for stdout, the default"},
}
# pydantic-settings reads one argument as None, "null" by default, and can't be told not to. No argument can hold
# a NUL character, so with this one none is read as None: -j null stays text, and -i null names a file.
_NONE_ARGUMENT: Final = "\0"

type StandardStream = Literal["-"]


def parse_request_body(text: str) -> dict[str, Any]:
    """
    Raise ValueError unless the text is a JSON object. The service checks the content,
    so the CLI can also send invalid bodies on purpose to show the service's 422s.
    """
    try:
        body = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"not valid JSON: {error}") from error
    except RecursionError as error:
        raise ValueError(f"nested too deeply: {error}") from error
    if not isinstance(body, dict):
        raise ValueError("must be a JSON object")
    return body


def _check_request_body(text: str) -> str:
    parse_request_body(text)
    return text


RequestBodyText = Annotated[str, AfterValidator(_check_request_body)]


def _check_service_url(url: HttpUrl) -> HttpUrl:
    # The CLI appends /payload to the URL's path, which a query or a fragment would swallow.
    if url.query or url.fragment:
        raise ValueError("must not have a query or a fragment")
    return url


ServiceUrl = Annotated[HttpUrl, AfterValidator(_check_service_url)]


def _check_writable_path(path: Path) -> Path:
    if path.is_dir():
        raise ValueError(f"{path} is a directory")
    if not path.parent.is_dir():
        raise ValueError(f"{path.parent} is not a directory")
    return path


WritablePath = Annotated[Path, AfterValidator(_check_writable_path)]


def _stream_or_path(value: Any) -> str:
    return "stream" if value == "-" else "path"


# The discriminator checks a value against the one member it selects, so a bad path gets one error, not one per member.
type StreamOr[PathType] = Annotated[
    Annotated[StandardStream, Tag("stream")] | Annotated[PathType, Tag("path")],
    Discriminator(_stream_or_path),
]


class CliSettings(BaseSettings):
    """Send one payload request to the caching service, --repeat times, and write each answer as a JSON line."""

    host: ServiceUrl = Field(HttpUrl(_DEFAULT_HOST), validation_alias=AliasChoices("host", "h"))
    repeat: PositiveInt = Field(_DEFAULT_REPEAT, validation_alias=AliasChoices("repeat", "r"))
    input_path: StreamOr[FilePath] | None = Field(None, validation_alias=AliasChoices("input", "i"))
    json_text: RequestBodyText | None = Field(None, validation_alias=AliasChoices("json", "j"))
    output_path: StreamOr[WritablePath] = Field("-", validation_alias=AliasChoices("output", "o"))

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Arguments only: pydantic-settings puts the CLI source in front of these, and the environment source
        # would let an exported HOST set --host.
        return (init_settings,)

    @model_validator(mode="after")
    def _exactly_one_input(self) -> Self:
        if self.input_path is None and self.json_text is None:
            raise ValueError("one of --input and --json is required")
        if self.input_path is not None and self.json_text is not None:
            raise ValueError("--input and --json can't both be given")
        return self


def parse_settings(args: Sequence[str]) -> CliSettings:
    """Raise ValidationError for an invalid value; argparse exits with status 2 for an unknown flag."""
    # pydantic-settings adds -h/--help only to the parser it builds itself, so a parser of our own frees -h for
    # --host. Like pydantic-settings' parser, it refuses abbreviations: --rep 3 would otherwise pass for --repeat 3,
    # until a new flag made it ambiguous.
    parser = ArgumentParser(prog=PROG_NAME, description=CliSettings.__doc__, add_help=False, allow_abbrev=False)
    parser.add_argument("--help", action="help", help="show this help message and exit")
    source = CliSettingsSource[ArgumentParser](
        CliSettings, root_parser=parser, add_argument_method=_add_argument, cli_parse_none_str=_NONE_ARGUMENT
    )
    return CliApp.run(CliSettings, cli_args=list(args), cli_settings_source=source)


def _add_argument(parser: ArgumentParser, *names: str, **kwargs: Any) -> Action:
    return parser.add_argument(*names, **(kwargs | _ARGUMENT_HELP[kwargs["dest"]]))
