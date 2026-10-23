from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from payload_cache.exceptions import BaseError


@dataclass(frozen=True)
class NewPayload:
    output: str


class PayloadNotFoundError(BaseError):
    default_code = "payload_not_found"
    default_message = "Payload not found."

    def __init__(self, payload_id: UUID) -> None:
        super().__init__(details={"payload_id": str(payload_id)})


class PayloadGateway(ABC):
    @abstractmethod
    async def add(self, new_payload: NewPayload) -> UUID:
        pass

    @abstractmethod
    async def find_output(self, payload_id: UUID) -> str | None:
        """Return the payload's output, or None if no payload has this id."""
