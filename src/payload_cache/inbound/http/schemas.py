from uuid import UUID

from pydantic import BaseModel, ConfigDict


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

    list_1: list[str]
    list_2: list[str]


class CreatePayloadResponse(BaseModel):
    id: UUID
    message: str


class PayloadResponse(BaseModel):
    output: str
