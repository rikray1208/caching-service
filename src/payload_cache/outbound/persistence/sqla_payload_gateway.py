from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payload_cache.application.ports.payload_gateway import NewPayload, PayloadGateway
from payload_cache.outbound.persistence.models import Payload


class SqlaPayloadGateway(PayloadGateway):
    """
    Each method is its own short transaction, so the services never commit
    and no request keeps a connection checked out while the transformer runs.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, new_payload: NewPayload) -> UUID:
        async with self._session_factory.begin() as session:
            result = await session.execute(insert(Payload).values(output=new_payload.output).returning(Payload.id))
            return result.scalar_one()

    async def find_output(self, payload_id: UUID) -> str | None:
        async with self._session_factory.begin() as session:
            return await session.scalar(select(Payload.output).where(Payload.id == payload_id))
