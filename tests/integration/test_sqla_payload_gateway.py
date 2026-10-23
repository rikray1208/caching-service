import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payload_cache.application.ports.payload_gateway import NewPayload
from payload_cache.outbound.persistence.sqla_payload_gateway import SqlaPayloadGateway


@pytest.fixture
def gateway(it_db_clean: None, it_sessionmaker: async_sessionmaker[AsyncSession]) -> SqlaPayloadGateway:
    return SqlaPayloadGateway(it_sessionmaker)


async def test_stored_output_is_found_by_the_payload_id(gateway: SqlaPayloadGateway) -> None:
    payload_id = await gateway.add(NewPayload(output="FIRST STRING, OTHER STRING"))

    assert await gateway.find_output(payload_id) == "FIRST STRING, OTHER STRING"


async def test_payload_id_is_a_uuidv7_from_the_database(gateway: SqlaPayloadGateway) -> None:
    payload_id = await gateway.add(NewPayload(output="FIRST STRING, OTHER STRING"))

    assert payload_id.version == 7


async def test_unknown_id_has_no_output(gateway: SqlaPayloadGateway) -> None:
    await gateway.add(NewPayload(output="FIRST STRING, OTHER STRING"))

    assert await gateway.find_output(uuid.uuid7()) is None
