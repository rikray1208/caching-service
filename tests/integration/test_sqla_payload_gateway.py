import uuid
from typing import Final

import anyio
import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.payload.application.ports.payload_gateway import NewPayload, StoredPayload
from app.payload.outbound.persistence.models import Payload
from app.payload.outbound.persistence.sqla_payload_gateway import SqlaPayloadGateway

FINGERPRINT: Final = "f" * 64
OTHER_FINGERPRINT: Final = "e" * 64


@pytest.fixture
def gateway(it_db_clean: None, it_sessionmaker: async_sessionmaker[AsyncSession]) -> SqlaPayloadGateway:
    return SqlaPayloadGateway(it_sessionmaker)


async def test_stored_output_is_found_by_the_payload_id(gateway: SqlaPayloadGateway) -> None:
    stored = await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="FIRST STRING, OTHER STRING"))

    assert stored.created is True
    assert await gateway.find_output(stored.id) == "FIRST STRING, OTHER STRING"


async def test_payload_id_is_a_uuidv7_from_the_database(gateway: SqlaPayloadGateway) -> None:
    stored = await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="FIRST STRING, OTHER STRING"))

    assert stored.id.version == 7


async def test_unknown_id_has_no_output(gateway: SqlaPayloadGateway) -> None:
    await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="FIRST STRING, OTHER STRING"))

    assert await gateway.find_output(uuid.uuid7()) is None


async def test_the_id_is_found_by_the_fingerprint_and_an_unknown_one_has_none(gateway: SqlaPayloadGateway) -> None:
    stored = await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="A, B"))

    assert await gateway.find_id(FINGERPRINT) == stored.id
    assert await gateway.find_id(OTHER_FINGERPRINT) is None


async def test_adding_a_stored_fingerprint_returns_its_payload_and_keeps_its_output(
    gateway: SqlaPayloadGateway,
) -> None:
    first = await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="stored first"))

    second = await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="stored second"))

    assert second == StoredPayload(id=first.id, created=False)
    assert await gateway.find_output(first.id) == "stored first"


async def test_concurrent_adds_of_one_fingerprint_get_one_id(gateway: SqlaPayloadGateway) -> None:
    stored: list[StoredPayload] = []

    async def add(output: str) -> None:
        stored.append(await gateway.add(NewPayload(fingerprint=FINGERPRINT, output=output)))

    async with anyio.create_task_group() as group:
        group.start_soon(add, "first")
        group.start_soon(add, "second")

    assert len({payload.id for payload in stored}) == 1
    assert sorted(payload.created for payload in stored) == [False, True]


async def test_add_waits_for_a_concurrent_transaction_with_the_fingerprint_and_returns_its_payload(
    gateway: SqlaPayloadGateway, it_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    # Two adds started together may still run one after the other. Holding this transaction open
    # makes add meet an uncommitted row with its fingerprint for certain.
    stored: list[StoredPayload] = []

    async def add() -> None:
        stored.append(await gateway.add(NewPayload(fingerprint=FINGERPRINT, output="stored second")))

    async with anyio.create_task_group() as group:
        async with it_sessionmaker.begin() as session:
            insert_payload = (
                insert(Payload).values(fingerprint=FINGERPRINT, output="stored first").returning(Payload.id)
            )
            other_id = (await session.execute(insert_payload)).scalar_one()
            group.start_soon(add)
            await _wait_until_another_session_waits_for(session)
            assert stored == []

    assert stored == [StoredPayload(id=other_id, created=False)]
    assert await gateway.find_output(other_id) == "stored first"


async def test_transactions_run_at_read_committed_whatever_the_session_default(it_engine: AsyncEngine) -> None:
    async with it_engine.connect() as connection:
        await connection.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        await connection.commit()

        assert await connection.scalar(text("SHOW transaction_isolation")) == "read committed"


async def _wait_until_another_session_waits_for(session: AsyncSession) -> None:
    # Polls, since only PostgreSQL knows and no Event can tell. pg_locks is read live, while pg_stat_activity
    # would stay as it was when this transaction first read it.
    is_waited_for = text(
        "SELECT EXISTS (SELECT FROM pg_locks WHERE NOT granted AND pg_backend_pid() = ANY(pg_blocking_pids(pid)))"
    )
    with anyio.fail_after(5):
        while not await session.scalar(is_waited_for):  # noqa: ASYNC110
            await anyio.sleep(0.01)
