"""Application configuration (env-driven via pydantic-settings)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCADE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://arcade:arcade@localhost:5432/arcade"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = Field(default=500, ge=10, le=5_000)
    cors_origins: str = "*"
    allowed_hosts: str = "localhost,127.0.0.1,testserver,backend,api.slackarcaide.com"
    trust_forwarded_client_ip: bool = False
    public_base_url: str = "https://api.slackarcaide.com"
    metrics_bearer_token: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def mcp_allowed_host_list(self) -> list[str]:
        """MCP validates the raw Host header, including its optional port."""
        hosts = self.allowed_host_list
        return [value for host in hosts for value in (host, f"{host}:*")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
