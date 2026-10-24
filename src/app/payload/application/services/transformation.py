import logging
from collections.abc import Collection

import anyio

from app.payload.application.ports.transformation_cache import TransformationCache
from app.payload.application.ports.transformer import Transformer, TransformerUnavailableError

logger = logging.getLogger(__name__)


class TransformationService:
    """Takes each transformation from the cache, and from the transformer only for the texts the cache lacks."""

    def __init__(self, transformer: Transformer, cache: TransformationCache) -> None:
        self._transformer = transformer
        self._cache = cache

    async def transform_all(self, texts: Collection[str]) -> dict[str, str]:
        """
        Raise TransformerUnavailableError if any call failed, after saving the calls that succeeded,
        so a retry calls the transformer only for the texts that failed.
        Any other exception from the transformer is a bug: it cancels the other calls, and arrives in an ExceptionGroup.
        """
        distinct_texts = list(dict.fromkeys(texts))
        cached = await self._cache.find(distinct_texts)
        missing = [text for text in distinct_texts if text not in cached]

        transformed: dict[str, str] = {}
        failures: list[TransformerUnavailableError] = []
        async with anyio.create_task_group() as group:
            for text in missing:
                group.start_soon(self._transform_one, text, transformed, failures)

        await self._cache.save(transformed)
        logger.info(
            "%d texts, %d distinct: %d from cache, %d transformed, %d failed",
            len(texts),
            len(distinct_texts),
            len(cached),
            len(transformed),
            len(failures),
        )
        if failures:
            logger.warning("%d of %d transformer calls failed", len(failures), len(missing), exc_info=failures[0])
            # A new error, so that the client gets the port's message whatever an adapter put into its own.
            raise TransformerUnavailableError() from failures[0]
        return cached | transformed

    async def _transform_one(
        self, text: str, transformed: dict[str, str], failures: list[TransformerUnavailableError]
    ) -> None:
        # Only this error is caught, so that a failure stops no other call; anything else is a bug.
        try:
            transformed[text] = await self._transformer.transform(text)
        except TransformerUnavailableError as error:
            failures.append(error)
