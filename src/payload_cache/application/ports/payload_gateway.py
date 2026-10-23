from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from payload_cache.exceptions import BaseError


@dataclass(frozen=True)
class NewPayload:
    fingerprint: str
    output: str


@dataclass(frozen=True)
class StoredPayload:
    id: UUID
    created: bool  # False: the input had a payload already, and `id` is that payload's


class PayloadNotFoundError(BaseError):
    default_code = "payload_not_found"
    default_message = "Payload not found."

    def __init__(self, payload_id: UUID) -> None:
        super().__init__(details={"payload_id": str(payload_id)})


class PayloadGateway(ABC):
    @abstractmethod
    async def find_id(self, fingerprint: str) -> UUID | None:
        """Return the id of the payload generated from the input with this fingerprint, or None if there is none."""

    @abstractmethod
    async def add(self, new_payload: NewPayload) -> StoredPayload:
        """
        Store the payload unless its fingerprint already has one, and return the fingerprint's payload either way.
        This, not find_id, guarantees id reuse: a concurrent request with the same input may store it first.
        """

    @abstractmethod
    async def find_output(self, payload_id: UUID) -> str | None:
        """Return the payload's output, or None if no payload has this id."""
