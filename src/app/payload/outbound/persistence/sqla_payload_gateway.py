from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.payload.application.ports.payload_gateway import NewPayload, PayloadGateway, StoredPayload
from app.payload.outbound.persistence.models import Payload


class SqlaPayloadGateway(PayloadGateway):
    """
    Each method is its own short transaction, so the services never commit
    and no request keeps a connection checked out while the transformer runs.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_id(self, fingerprint: str) -> UUID | None:
        async with self._session_factory.begin() as session:
            return await session.scalar(select(Payload.id).where(Payload.fingerprint == fingerprint))

    async def add(self, new_payload: NewPayload) -> StoredPayload:
        """
        Relies on READ COMMITTED, PostgreSQL's default: the INSERT waits for a concurrent transaction
        with the same fingerprint, and the SELECT, as a new statement, sees the row it committed.
        """
        insert_payload = (
            insert(Payload)
            .values(fingerprint=new_payload.fingerprint, output=new_payload.output)
            .on_conflict_do_nothing(index_elements=["fingerprint"])
            .returning(Payload.id)
        )
        select_id = select(Payload.id).where(Payload.fingerprint == new_payload.fingerprint)
        async with self._session_factory.begin() as session:
            created_id = (await session.execute(insert_payload)).scalar_one_or_none()
            if created_id is not None:
                return StoredPayload(id=created_id, created=True)
            existing_id = (await session.execute(select_id)).scalar_one()
            return StoredPayload(id=existing_id, created=False)

    async def find_output(self, payload_id: UUID) -> str | None:
        async with self._session_factory.begin() as session:
            return await session.scalar(select(Payload.output).where(Payload.id == payload_id))
