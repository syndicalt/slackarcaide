"""Application configuration (env-driven via pydantic-settings)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARCADE_", env_file=".env", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://arcade:arcade@localhost:5432/arcade"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
