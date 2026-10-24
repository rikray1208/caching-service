from typing import Literal

from pydantic import Field, NonNegativeFloat
from pydantic_settings import BaseSettings

from app.common.outbound.persistence.settings import DatabaseSettings

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    transformer_delay: NonNegativeFloat = Field(0, allow_inf_nan=False)  # seconds per call of the stand-in
    logging_level: LogLevel = "INFO"
