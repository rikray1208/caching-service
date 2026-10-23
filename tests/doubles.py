import uuid
from collections import Counter
from collections.abc import Collection, Mapping
from typing import ClassVar

from sqlalchemy import QueuePool

from payload_cache.application.ports.payload_gateway import NewPayload, PayloadGateway
from payload_cache.application.ports.transformation_cache import TransformationCache
from payload_cache.application.ports.transformer import Transformer


class StubCrashError(Exception):
    """Not a BaseError: the error table doesn't know it, so it stands for a bug."""


class StubCrashingTransformer(Transformer):
    CRASH_TEXT: ClassVar[str] = "stub crash details that must stay in the log"

    async def transform(self, text: str) -> str:
        raise StubCrashError(self.CRASH_TEXT)


class SpyTransformer(Transformer):
    """Uppercases, as the stand-in does, and counts the calls per text."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    async def transform(self, text: str) -> str:
        self.calls[text] += 1
        return text.upper()


class SpyPoolTransformer(Transformer):
    """Records the pool's checked-out connections during each call: a transaction held across the call shows as one."""

    def __init__(self, pool: QueuePool) -> None:
        self._pool = pool
        self.checked_out_connections: list[int] = []

    async def transform(self, text: str) -> str:
        self.checked_out_connections.append(self._pool.checkedout())
        return text.upper()


class FakeTransformationCache(TransformationCache):
    def __init__(self, transformations: Mapping[str, str] | None = None) -> None:
        self.transformations = dict(transformations or {})

    async def find(self, texts: Collection[str]) -> dict[str, str]:
        return {text: self.transformations[text] for text in texts if text in self.transformations}

    async def save(self, transformations: Mapping[str, str]) -> None:
        for text, result in transformations.items():
            self.transformations.setdefault(text, result)


class FakePayloadGateway(PayloadGateway):
    def __init__(self) -> None:
        self.outputs: dict[uuid.UUID, str] = {}

    async def add(self, new_payload: NewPayload) -> uuid.UUID:
        payload_id = uuid.uuid7()
        self.outputs[payload_id] = new_payload.output
        return payload_id

    async def find_output(self, payload_id: uuid.UUID) -> str | None:
        return self.outputs.get(payload_id)
