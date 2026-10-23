import json
from collections.abc import Sequence
from typing import Annotated, Any, Final

from pydantic import AfterValidator, AliasChoices, Field, HttpUrl, PositiveInt
from pydantic_settings import BaseSettings, CliApp, PydanticBaseSettingsSource, SettingsConfigDict

PROG_NAME: Final = "cache-cli"


def parse_request_body(text: str) -> dict[str, Any]:
    """
    Raise ValueError unless the text is a JSON object. The service checks the content,
    so the CLI can also send invalid bodies on purpose to show the service's 422s.
    """
    try:
        body = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"not valid JSON: {error}") from error
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


class CliSettings(BaseSettings):
    """Send one payload request to the caching service, --repeat times, and write each answer as a JSON line."""

    model_config = SettingsConfigDict(cli_prog_name=PROG_NAME)

    host: ServiceUrl = Field(HttpUrl("http://localhost:8000"), description="The caching service's URL.")
    repeat: PositiveInt = Field(
        1, validation_alias=AliasChoices("repeat", "r"), description="How many rounds of POST and GET to send."
    )
    json_text: RequestBodyText = Field(
        validation_alias=AliasChoices("json", "j"), description="The request body: a JSON object."
    )

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


def parse_settings(args: Sequence[str]) -> CliSettings:
    """Raise ValidationError for an invalid value; argparse exits with status 2 for an unknown flag."""
    return CliApp.run(CliSettings, cli_args=list(args))
