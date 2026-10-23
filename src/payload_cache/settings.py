from typing import Literal

from pydantic import Field, NonNegativeFloat
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str
    port: int
    user: str
    password: str
    db: str

    def create_url(self, drivername: str = "postgresql+asyncpg") -> URL:
        return URL.create(
            drivername=drivername,
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db,
        )

    def create_string_url(self) -> str:
        # Alembic's config is a ConfigParser, which would read a "%" in the password as interpolation.
        return self.create_url().render_as_string(hide_password=False).replace("%", "%%")


class Settings(BaseSettings):
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    transformer_delay: NonNegativeFloat = Field(0, allow_inf_nan=False)  # seconds per call of the stand-in
    logging_level: LogLevel = "INFO"
