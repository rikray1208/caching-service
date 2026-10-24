from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

MAX_TEXTS_PER_LIST: Final = 1_000
MAX_TEXT_LENGTH: Final = 1_000


def _reject_nul(text: str) -> str:
    if "\x00" in text:
        raise ValueError("Text must not contain \\u0000, which PostgreSQL can't store.")
    return text


# A lone surrogate such as "\ud800" never reaches _reject_nul: to check max_length, pydantic-core decodes
# the text as UTF-8, and that fails with string_unicode.
Text = Annotated[str, StringConstraints(max_length=MAX_TEXT_LENGTH), AfterValidator(_reject_nul)]
TextList = Annotated[list[Text], Field(min_length=1, max_length=MAX_TEXTS_PER_LIST)]


class CreatePayloadRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "list_1": ["first string", "second string", "third string"],
                    "list_2": ["other string", "another string", "last string"],
                }
            ]
        }
    )

    list_1: TextList
    list_2: TextList


class CreatePayloadResponse(BaseModel):
    id: UUID
    message: str


class PayloadResponse(BaseModel):
    output: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str | None
    message: str
    details: dict[str, Any] | None = None
