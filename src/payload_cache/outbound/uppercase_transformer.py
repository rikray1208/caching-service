import anyio

from payload_cache.application.ports.transformer import Transformer


class UppercaseTransformer(Transformer):
    """
    The stand-in for the external service that the task asks for.
    `delay` holds each call for that many seconds, as a network call would, so the cache shows in timings.
    """

    def __init__(self, delay: float = 0) -> None:
        self._delay = delay

    async def transform(self, text: str) -> str:
        await anyio.sleep(self._delay)
        return text.upper()
