from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class NewPayload:
    output: str


class PayloadGateway(ABC):
    @abstractmethod
    async def add(self, new_payload: NewPayload) -> UUID:
        pass

    @abstractmethod
    async def find_output(self, payload_id: UUID) -> str | None:
        """Return the payload's output, or None if no payload has this id."""
