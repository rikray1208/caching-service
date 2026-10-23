from abc import ABC, abstractmethod


class Transformer(ABC):
    """The external service: one text per call, and every call costs."""

    @abstractmethod
    async def transform(self, text: str) -> str:
        pass
