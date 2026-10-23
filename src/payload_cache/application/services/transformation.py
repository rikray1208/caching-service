import logging
from collections.abc import Collection

from payload_cache.application.ports.transformation_cache import TransformationCache
from payload_cache.application.ports.transformer import Transformer

logger = logging.getLogger(__name__)


class TransformationService:
    """Takes each transformation from the cache, and from the transformer only for the texts the cache lacks."""

    def __init__(self, transformer: Transformer, cache: TransformationCache) -> None:
        self._transformer = transformer
        self._cache = cache

    async def transform_all(self, texts: Collection[str]) -> dict[str, str]:
        distinct_texts = list(dict.fromkeys(texts))
        cached = await self._cache.find(distinct_texts)

        transformed: dict[str, str] = {}
        for text in distinct_texts:
            if text not in cached:
                transformed[text] = await self._transformer.transform(text)

        await self._cache.save(transformed)
        logger.info(
            "%d texts, %d distinct: %d from cache, %d transformed",
            len(texts),
            len(distinct_texts),
            len(cached),
            len(transformed),
        )
        return cached | transformed
