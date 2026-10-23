from abc import ABC, abstractmethod

from payload_cache.exceptions import BaseError


class TransformerUnavailableError(BaseError):
    default_code = "transformer_unavailable"
    default_message = "The transformer is unavailable. Try again later."


class Transformer(ABC):
    """The external service: one text per call, and every call costs."""

    @abstractmethod
    async def transform(self, text: str) -> str:
        """Raise TransformerUnavailableError when the service fails in a way that a later retry may fix."""
