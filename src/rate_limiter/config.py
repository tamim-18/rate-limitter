from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "production", "test"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
AlgorithmName = Literal["token_bucket", "fixed_window", "sliding_window_log", "leaky_bucket"]


class Settings(BaseSettings):
    """Application settings (environment variables only; no os.getenv elsewhere)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Field(default="development")
    log_level: LogLevel = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rate_limiter",
        description="Async SQLAlchemy URL (asyncpg driver)",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/")

    default_algorithm: AlgorithmName = "token_bucket"
    default_rate_limit: int = Field(default=100, gt=0)
    default_window_seconds: int = Field(default=60, gt=0)

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"

    @property
    def json_logs(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
