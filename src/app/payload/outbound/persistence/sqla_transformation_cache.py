import hashlib
from collections.abc import Collection, Mapping
from operator import itemgetter

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.payload.application.ports.transformation_cache import TransformationCache
from app.payload.outbound.persistence.models import Transformation


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SqlaTransformationCache(TransformationCache):
    """
    Each method is its own short transaction: the use case calls the transformer between them.
    Rows are keyed by the SHA-256 of the text's UTF-8 bytes, because a B-tree index entry holds about 2.7 kB
    and 1,000 characters of four-byte UTF-8 take 4 kB. The request limits keep each statement far below
    asyncpg's 32,767 parameters: at most 2,000 in `find` and 6,000 in `save`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find(self, texts: Collection[str]) -> dict[str, str]:
        text_by_hash = {_text_hash(text): text for text in texts}
        statement = select(Transformation.text_hash, Transformation.result).where(
            Transformation.text_hash.in_(list(text_by_hash))
        )
        async with self._session_factory.begin() as session:
            rows = await session.execute(statement)
            return {text_by_hash[text_hash]: result for text_hash, result in rows}

    async def save(self, transformations: Mapping[str, str]) -> None:
        if not transformations:
            return
        # Sorted by key, so that two requests saving overlapping texts lock them in the same order and can't deadlock.
        rows = sorted(
            (
                {"text_hash": _text_hash(text), "text": text, "result": result}
                for text, result in transformations.items()
            ),
            key=itemgetter("text_hash"),
        )
        statement = insert(Transformation).values(rows).on_conflict_do_nothing(index_elements=["text_hash"])
        async with self._session_factory.begin() as session:
            await session.execute(statement)
