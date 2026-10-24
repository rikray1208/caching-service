from collections import Counter

import pytest

from app.payload.application.payload_input import PayloadInput
from app.payload.application.ports.payload_gateway import StoredPayload
from app.payload.application.ports.transformer import TransformerUnavailableError
from app.payload.application.services.payload import PayloadService
from app.payload.application.services.transformation import TransformationService
from tests.doubles import (
    FakePayloadGateway,
    FakeRacingPayloadGateway,
    FakeTransformationCache,
    SpyTransformer,
    StubFailingTransformer,
)


async def test_texts_of_an_earlier_payload_do_not_reach_the_transformer_again() -> None:
    spy = SpyTransformer()
    service = PayloadService(TransformationService(spy, FakeTransformationCache()), FakePayloadGateway())

    await service.create(PayloadInput(list_1=("a", "b"), list_2=("c", "d")))
    stored = await service.create(PayloadInput(list_1=("c", "a"), list_2=("a", "e")))

    assert spy.calls == Counter(["a", "b", "c", "d", "e"])
    assert await service.get_output(stored.id) == "C, A, A, E"


async def test_an_input_seen_before_gets_the_same_id_without_a_transformer_call() -> None:
    gateway = FakePayloadGateway()
    earlier_service = PayloadService(TransformationService(SpyTransformer(), FakeTransformationCache()), gateway)
    created = await earlier_service.create(PayloadInput(list_1=("a",), list_2=("b",)))
    # An empty transformation cache, so that only the stored payload can spare the transformer.
    spy = SpyTransformer()
    service = PayloadService(TransformationService(spy, FakeTransformationCache()), gateway)

    reused = await service.create(PayloadInput(list_1=("a",), list_2=("b",)))

    assert created.created is True
    assert reused == StoredPayload(id=created.id, created=False)
    assert spy.calls == Counter()


async def test_an_input_stored_after_the_lookup_gets_the_stored_id() -> None:
    service = PayloadService(
        TransformationService(SpyTransformer(), FakeTransformationCache()), FakeRacingPayloadGateway()
    )
    stored_first = await service.create(PayloadInput(list_1=("a",), list_2=("b",)))

    stored_second = await service.create(PayloadInput(list_1=("a",), list_2=("b",)))

    assert stored_second == StoredPayload(id=stored_first.id, created=False)


async def test_a_different_input_with_the_same_output_gets_a_new_payload() -> None:
    service = PayloadService(TransformationService(SpyTransformer(), FakeTransformationCache()), FakePayloadGateway())

    lower = await service.create(PayloadInput(list_1=("a",), list_2=("b",)))
    upper = await service.create(PayloadInput(list_1=("A",), list_2=("B",)))

    assert upper.created is True
    assert upper.id != lower.id
    assert await service.get_output(upper.id) == await service.get_output(lower.id) == "A, B"


async def test_a_transformer_failure_stores_no_payload() -> None:
    gateway = FakePayloadGateway()
    service = PayloadService(TransformationService(StubFailingTransformer("b"), FakeTransformationCache()), gateway)

    with pytest.raises(TransformerUnavailableError):
        await service.create(PayloadInput(list_1=("a",), list_2=("b",)))

    assert gateway.outputs == {}
