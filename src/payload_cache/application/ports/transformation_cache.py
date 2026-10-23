from abc import ABC, abstractmethod
from collections.abc import Collection, Mapping


class TransformationCache(ABC):
    """What the transformer returned before, keyed by the exact text: no trimming, case folding or normalization."""

    @abstractmethod
    async def find(self, texts: Collection[str]) -> dict[str, str]:
        """Return the stored transformation of each text that has one; a text without one is absent."""

    @abstractmethod
    async def save(self, transformations: Mapping[str, str]) -> None:
        """
        Store new transformations.
        A text that a concurrent request stored first keeps its result, and the call succeeds.
        """
