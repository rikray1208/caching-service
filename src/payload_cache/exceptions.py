from typing import Any, ClassVar


class BaseError(Exception):
    default_code: ClassVar[str | None] = None
    default_message: ClassVar[str | None] = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        msg = message if message is not None else self.default_message
        super().__init__() if msg is None else super().__init__(msg)
        self.code = code if code is not None else self.default_code
        self.details = details
        if details:
            self.add_note(f"details: {details}")
