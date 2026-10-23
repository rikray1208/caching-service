import logging
from collections import Counter

import pytest

from payload_cache.application.services.transformation import TransformationService
from tests.doubles import FakeTransformationCache, SpyTransformer


async def test_a_repeated_text_reaches_the_transformer_once() -> None:
    spy = SpyTransformer()
    service = TransformationService(spy, FakeTransformationCache())

    transformations = await service.transform_all(["a", "b", "a", "a"])

    assert transformations == {"a": "A", "b": "B"}
    assert spy.calls == Counter(["a", "b"])


async def test_a_cached_text_does_not_reach_the_transformer() -> None:
    spy = SpyTransformer()
    service = TransformationService(spy, FakeTransformationCache({"a": "cached a"}))

    transformations = await service.transform_all(["a", "b"])

    assert transformations == {"a": "cached a", "b": "B"}
    assert spy.calls == Counter(["b"])


async def test_overlapping_calls_reach_the_transformer_only_for_their_new_texts() -> None:
    spy = SpyTransformer()
    cache = FakeTransformationCache()
    service = TransformationService(spy, cache)

    await service.transform_all(["a", "b"])
    transformations = await service.transform_all(["b", "c"])

    assert transformations == {"b": "B", "c": "C"}
    assert spy.calls == Counter(["a", "b", "c"])
    assert cache.transformations == {"a": "A", "b": "B", "c": "C"}


async def test_one_info_line_says_where_the_transformations_came_from(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    service = TransformationService(SpyTransformer(), FakeTransformationCache({"a": "A"}))

    await service.transform_all(["a", "b", "b", "c"])

    assert caplog.messages == ["4 texts, 3 distinct: 1 from cache, 2 transformed"]
