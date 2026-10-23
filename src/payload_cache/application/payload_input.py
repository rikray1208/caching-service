from collections.abc import Mapping
from dataclasses import dataclass
from itertools import chain


@dataclass(frozen=True, slots=True)
class PayloadInput:
    """The two lists of one request. Their texts pair up by position."""

    list_1: tuple[str, ...]
    list_2: tuple[str, ...]

    def texts(self) -> list[str]:
        return [*self.list_1, *self.list_2]

    def render(self, transformations: Mapping[str, str]) -> str:
        """
        Interleave the transformed texts, list_1[0], list_2[0], list_1[1], ..., joined with ", " as in the task's sample.
        A KeyError means the caller didn't transform every text: a bug, not an input error.
        """
        pairs = zip(self.list_1, self.list_2, strict=True)
        return ", ".join(transformations[text] for text in chain.from_iterable(pairs))
