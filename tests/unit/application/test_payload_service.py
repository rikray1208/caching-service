from collections import Counter

from payload_cache.application.payload_input import PayloadInput
from payload_cache.application.services.payload import PayloadService
from payload_cache.application.services.transformation import TransformationService
from tests.doubles import FakePayloadGateway, FakeTransformationCache, SpyTransformer


async def test_texts_of_an_earlier_payload_do_not_reach_the_transformer_again() -> None:
    spy = SpyTransformer()
    service = PayloadService(TransformationService(spy, FakeTransformationCache()), FakePayloadGateway())

    await service.create(PayloadInput(list_1=("a", "b"), list_2=("c", "d")))
    payload_id = await service.create(PayloadInput(list_1=("c", "a"), list_2=("a", "e")))

    assert spy.calls == Counter(["a", "b", "c", "d", "e"])
    assert await service.get_output(payload_id) == "C, A, A, E"
