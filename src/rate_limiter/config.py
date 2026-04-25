from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings (environment variables only; no os.getenv elsewhere)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(default="development", description="development | production")
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rate_limiter",
        description="Async SQLAlchemy URL (asyncpg driver)",
    )
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    default_algorithm: str = "token_bucket"
    default_rate_limit: int = 100
    default_window_seconds: int = 60

    @property
    def docs_enabled(self) -> bool:
        return self.environment.lower() != "production"

    @property
    def json_logs(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
