from typing import ClassVar

from payload_cache.application.ports.transformer import Transformer


class StubCrashError(Exception):
    """Not a BaseError: the error table doesn't know it, so it stands for a bug."""


class StubCrashingTransformer(Transformer):
    CRASH_TEXT: ClassVar[str] = "stub crash details that must stay in the log"

    async def transform(self, text: str) -> str:
        raise StubCrashError(self.CRASH_TEXT)
