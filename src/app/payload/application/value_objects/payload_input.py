import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import chain

from app.common.exceptions import BaseError


class UnequalListsError(BaseError):
    default_code = "unequal_lists"
    default_message = "list_1 and list_2 must have the same length."


@dataclass(frozen=True, slots=True)
class PayloadInput:
    list_1: tuple[str, ...]
    list_2: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.list_1) != len(self.list_2):
            raise UnequalListsError(details={"list_1_length": len(self.list_1), "list_2_length": len(self.list_2)})

    def texts(self) -> list[str]:
        return [*self.list_1, *self.list_2]

    def fingerprint(self) -> str:
        canonical_json = json.dumps([self.list_1, self.list_2], ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("ascii")).hexdigest()

    def render(self, transformations: Mapping[str, str]) -> str:
        pairs = zip(self.list_1, self.list_2, strict=True)
        return ", ".join(transformations[text] for text in chain.from_iterable(pairs))
