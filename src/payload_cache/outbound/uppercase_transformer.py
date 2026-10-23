from payload_cache.application.ports.transformer import Transformer


class UppercaseTransformer(Transformer):
    """The stand-in for the external service that the task asks for."""

    async def transform(self, text: str) -> str:
        return text.upper()
