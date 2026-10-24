import uuid
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from typing import ClassVar

import anyio
import httpx2
from sqlalchemy import QueuePool

from app.cli.client import PayloadClient
from app.payload.application.ports.payload_gateway import NewPayload, PayloadGateway, StoredPayload
from app.payload.application.ports.transformation_cache import TransformationCache
from app.payload.application.ports.transformer import Transformer, TransformerUnavailableError


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


class SpyHoldingTransformer(SpyTransformer):
    """Holds every call until `expected_calls` calls have started, so it returns only if the calls run concurrently."""

    def __init__(self, expected_calls: int) -> None:
        super().__init__()
        self._expected_calls = expected_calls
        self._all_started = anyio.Event()

    async def transform(self, text: str) -> str:
        transformed = await super().transform(text)
        if self.calls.total() == self._expected_calls:
            self._all_started.set()
        await self._all_started.wait()
        return transformed


class StubCrashingHoldingTransformer(SpyHoldingTransformer):
    """
    Once `expected_calls` calls have started, the call for `crash_text` crashes, and the others stay held
    until they are cancelled, which `cancelled` counts.
    """

    def __init__(self, crash_text: str, expected_calls: int) -> None:
        super().__init__(expected_calls)
        self._crash_text = crash_text
        self.cancelled: Counter[str] = Counter()

    async def transform(self, text: str) -> str:
        try:
            await super().transform(text)
            if text != self._crash_text:
                await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            self.cancelled[text] += 1
            raise
        raise StubCrashError(StubCrashingTransformer.CRASH_TEXT)


class StubFailingTransformer(SpyTransformer):
    """
    Fails for the chosen texts as a retry may fix, and otherwise uppercases; counts every call, failed or not.
    Each call yields once before it answers, so that a failure lands while the other calls are still running.
    """

    FAILURE_TEXT: ClassVar[str] = "stub failure details that must stay in the log"

    def __init__(self, *failing_texts: str) -> None:
        super().__init__()
        self._failing_texts = frozenset(failing_texts)

    async def transform(self, text: str) -> str:
        transformed = await super().transform(text)
        await anyio.lowlevel.checkpoint()
        if text in self._failing_texts:
            raise TransformerUnavailableError(self.FAILURE_TEXT)
        return transformed


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
        self.ids: dict[str, uuid.UUID] = {}
        self.outputs: dict[uuid.UUID, str] = {}

    async def find_id(self, fingerprint: str) -> uuid.UUID | None:
        return self.ids.get(fingerprint)

    async def add(self, new_payload: NewPayload) -> StoredPayload:
        if (payload_id := self.ids.get(new_payload.fingerprint)) is not None:
            return StoredPayload(id=payload_id, created=False)
        payload_id = uuid.uuid7()
        self.ids[new_payload.fingerprint] = payload_id
        self.outputs[payload_id] = new_payload.output
        return StoredPayload(id=payload_id, created=True)

    async def find_output(self, payload_id: uuid.UUID) -> str | None:
        return self.outputs.get(payload_id)


class FakeRacingPayloadGateway(FakePayloadGateway):
    """Its lookup misses every input, as if a concurrent request stored the input just after the lookup."""

    async def find_id(self, fingerprint: str) -> uuid.UUID | None:
        return None


class FakePayloadApi:
    """Answers like the service's HTTP API: 201 for a body it hasn't seen, 200 with the same id after that."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self._ids: dict[bytes, str] = {}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.method == "GET":
            return httpx2.Response(200, json={"output": "A, B"})
        if (payload_id := self._ids.get(request.content)) is not None:
            return httpx2.Response(200, json={"id": payload_id, "message": "Payload already exists."})
        payload_id = self._ids[request.content] = f"payload-{len(self._ids) + 1}"
        return httpx2.Response(201, json={"id": payload_id, "message": "Payload created."})


def payload_client_for(handler: Callable[[httpx2.Request], httpx2.Response]) -> PayloadClient:
    """A PayloadClient whose requests the handler answers, at http://service.test."""
    return PayloadClient(httpx2.Client(transport=httpx2.MockTransport(handler), base_url="http://service.test"))
