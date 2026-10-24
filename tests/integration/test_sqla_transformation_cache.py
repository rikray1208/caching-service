import anyio
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.payload.outbound.persistence.sqla_transformation_cache import SqlaTransformationCache


@pytest.fixture
def cache(it_db_clean: None, it_sessionmaker: async_sessionmaker[AsyncSession]) -> SqlaTransformationCache:
    return SqlaTransformationCache(it_sessionmaker)


async def test_saved_transformations_are_found_and_a_miss_is_absent(cache: SqlaTransformationCache) -> None:
    await cache.save({"first string": "FIRST STRING", "last string": "LAST STRING"})

    found = await cache.find(["first string", "last string", "other string"])

    assert found == {"first string": "FIRST STRING", "last string": "LAST STRING"}


async def test_texts_are_matched_exactly(cache: SqlaTransformationCache) -> None:
    precomposed = "\N{LATIN SMALL LETTER E WITH ACUTE}"
    decomposed = "e\N{COMBINING ACUTE ACCENT}"
    await cache.save({"Straße": "STRASSE", precomposed: "É"})

    found = await cache.find(["Straße", "straße", "Strasse", " Straße", "Straße ", precomposed, decomposed])

    assert found == {"Straße": "STRASSE", precomposed: "É"}


async def test_a_text_of_1000_four_byte_characters_is_stored_and_found_again(cache: SqlaTransformationCache) -> None:
    text = "\N{GRINNING FACE}" * 1_000  # 4,000 bytes in UTF-8, more than a B-tree index entry holds

    await cache.save({text: "result"})

    assert await cache.find([text]) == {text: "result"}


async def test_a_text_stored_first_keeps_its_result_and_saving_it_again_succeeds(
    cache: SqlaTransformationCache,
) -> None:
    await cache.save({"a": "stored first"})

    await cache.save({"a": "stored second", "b": "B"})

    assert await cache.find(["a", "b"]) == {"a": "stored first", "b": "B"}


async def test_concurrent_saves_of_the_same_texts_in_opposite_orders_both_succeed(
    cache: SqlaTransformationCache,
) -> None:
    texts = [f"text {number}" for number in range(1_000)]

    async with anyio.create_task_group() as group:
        group.start_soon(cache.save, dict.fromkeys(texts, "first"))
        group.start_soon(cache.save, dict.fromkeys(reversed(texts), "second"))

    assert (await cache.find(texts)).keys() == set(texts)


async def test_saving_nothing_runs_no_statement(cache: SqlaTransformationCache, it_engine: AsyncEngine) -> None:
    statements: list[str] = []
    event.listen(it_engine.sync_engine, "before_cursor_execute", lambda _conn, _cursor, sql, *_: statements.append(sql))

    await cache.save({})

    assert statements == []
