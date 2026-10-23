import logging
from collections import Counter

import anyio
import pytest

from payload_cache.application.ports.transformer import TransformerUnavailableError
from payload_cache.application.services.transformation import TransformationService
from tests.doubles import (
    FakeTransformationCache,
    SpyHoldingTransformer,
    SpyTransformer,
    StubCrashError,
    StubCrashingHoldingTransformer,
    StubCrashingTransformer,
    StubFailingTransformer,
)


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


async def test_the_missing_texts_are_transformed_concurrently() -> None:
    spy = SpyHoldingTransformer(expected_calls=3)
    service = TransformationService(spy, FakeTransformationCache({"d": "cached d"}))

    with anyio.fail_after(1):
        transformations = await service.transform_all(["a", "b", "c", "d"])

    assert transformations == {"a": "A", "b": "B", "c": "C", "d": "cached d"}
    assert spy.calls == Counter(["a", "b", "c"])


async def test_one_info_line_says_where_the_transformations_came_from(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    service = TransformationService(SpyTransformer(), FakeTransformationCache({"a": "A"}))

    await service.transform_all(["a", "b", "b", "c"])

    assert caplog.messages == ["4 texts, 3 distinct: 1 from cache, 2 transformed, 0 failed"]


async def test_a_failed_call_stops_no_other_call_and_the_successes_are_saved() -> None:
    stub = StubFailingTransformer("b")
    cache = FakeTransformationCache({"d": "cached d"})
    service = TransformationService(stub, cache)

    with pytest.raises(TransformerUnavailableError):
        await service.transform_all(["a", "b", "c", "d"])

    assert stub.calls == Counter(["a", "b", "c"])
    assert cache.transformations == {"a": "A", "c": "C", "d": "cached d"}


async def test_a_retry_after_a_partial_failure_calls_only_the_failed_texts() -> None:
    cache = FakeTransformationCache()
    failing_service = TransformationService(StubFailingTransformer("b", "d"), cache)
    with pytest.raises(TransformerUnavailableError):
        await failing_service.transform_all(["a", "b", "c", "d"])
    spy = SpyTransformer()

    transformations = await TransformationService(spy, cache).transform_all(["a", "b", "c", "d"])

    assert spy.calls == Counter(["b", "d"])
    assert transformations == {"a": "A", "b": "B", "c": "C", "d": "D"}


async def test_failed_calls_are_counted_and_logged_as_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    service = TransformationService(StubFailingTransformer("b", "c"), FakeTransformationCache({"a": "A"}))

    with pytest.raises(TransformerUnavailableError):
        await service.transform_all(["a", "b", "c", "d"])

    assert [(record.levelno, record.getMessage()) for record in caplog.records] == [
        (logging.INFO, "4 texts, 4 distinct: 1 from cache, 1 transformed, 2 failed"),
        (logging.WARNING, "2 of 3 transformer calls failed"),
    ]
    warning_exc_info = caplog.records[1].exc_info
    assert warning_exc_info is not None
    assert str(warning_exc_info[1]) == StubFailingTransformer.FAILURE_TEXT


async def test_the_raised_error_has_the_port_s_message_whatever_the_adapter_s_says() -> None:
    service = TransformationService(StubFailingTransformer("a"), FakeTransformationCache())

    with pytest.raises(TransformerUnavailableError) as raised:
        await service.transform_all(["a"])

    assert str(raised.value) == "The transformer is unavailable. Try again later."
    assert str(raised.value.__cause__) == StubFailingTransformer.FAILURE_TEXT


async def test_any_other_exception_is_a_bug_and_not_taken_for_a_failure() -> None:
    service = TransformationService(StubCrashingTransformer(), FakeTransformationCache())

    with pytest.RaisesGroup(StubCrashError):
        await service.transform_all(["a"])


async def test_any_other_exception_cancels_the_calls_still_running() -> None:
    stub = StubCrashingHoldingTransformer("b", expected_calls=3)
    service = TransformationService(stub, FakeTransformationCache())

    with pytest.RaisesGroup(StubCrashError), anyio.fail_after(1):
        await service.transform_all(["a", "b", "c"])

    assert stub.cancelled == Counter(["a", "c"])
