import logging
from collections.abc import Collection, Mapping, Sized

import anyio
from anyio import TaskHandle

from app.payload.application.ports.transformation_cache import TransformationCache
from app.payload.application.ports.transformer import Transformer, TransformerUnavailableError

logger = logging.getLogger(__name__)


class TransformationService:
    def __init__(self, transformer: Transformer, cache: TransformationCache) -> None:
        self._transformer = transformer
        self._cache = cache

    async def transform_all(self, texts: Collection[str]) -> dict[str, str]:
        distinct_texts = list(dict.fromkeys(texts))
        cached = await self._cache.find(distinct_texts)
        missing = [text for text in distinct_texts if text not in cached]

        async with anyio.create_task_group() as group:
            handles = {text: group.start_soon(self._try_transform, text) for text in missing}
        transformed, failures = self._split_outcomes(handles)

        await self._cache.save(transformed)
        self._log_counts(texts=texts, distinct=distinct_texts, cached=cached, transformed=transformed, failed=failures)
        if failures:
            logger.warning("%d of %d transformer calls failed", len(failures), len(missing), exc_info=failures[0])
            raise TransformerUnavailableError() from failures[0]
        return cached | transformed

    async def _try_transform(self, text: str) -> str | TransformerUnavailableError:
        try:
            return await self._transformer.transform(text)
        except TransformerUnavailableError as error:
            return error

    @staticmethod
    def _split_outcomes(
        handles: Mapping[str, TaskHandle[str | TransformerUnavailableError]],
    ) -> tuple[dict[str, str], list[TransformerUnavailableError]]:
        outcomes = {text: handle.return_value for text, handle in handles.items()}
        transformed = {text: outcome for text, outcome in outcomes.items() if isinstance(outcome, str)}
        failures = [outcome for outcome in outcomes.values() if isinstance(outcome, TransformerUnavailableError)]
        return transformed, failures

    @staticmethod
    def _log_counts(*, texts: Sized, distinct: Sized, cached: Sized, transformed: Sized, failed: Sized) -> None:
        logger.info(
            "%d texts, %d distinct: %d from cache, %d transformed, %d failed",
            len(texts),
            len(distinct),
            len(cached),
            len(transformed),
            len(failed),
        )
