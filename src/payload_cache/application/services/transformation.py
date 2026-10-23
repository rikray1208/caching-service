from collections.abc import Iterable

from payload_cache.application.ports.transformer import Transformer


class TransformationService:
    def __init__(self, transformer: Transformer) -> None:
        self._transformer = transformer

    async def transform_all(self, texts: Iterable[str]) -> dict[str, str]:
        transformations: dict[str, str] = {}
        for text in texts:
            transformations[text] = await self._transformer.transform(text)
        return transformations
