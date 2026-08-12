"""Application configuration (env-driven via pydantic-settings)."""

from functools import cached_property, lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network

from pydantic import Field, field_validator
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
    trusted_edge_proxy_cidrs: str = ""
    public_base_url: str = "https://api.slackarcaide.com"
    metrics_bearer_token: str | None = None

    @field_validator("trusted_edge_proxy_cidrs")
    @classmethod
    def validate_proxy_cidrs(cls, value: str) -> str:
        for cidr in value.split(","):
            if cidr.strip():
                ip_network(cidr.strip(), strict=False)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @cached_property
    def trusted_edge_proxy_networks(self) -> tuple[IPv4Network | IPv6Network, ...]:
        return tuple(
            ip_network(cidr.strip(), strict=False)
            for cidr in self.trusted_edge_proxy_cidrs.split(",")
            if cidr.strip()
        )

    @property
    def mcp_allowed_host_list(self) -> list[str]:
        """MCP validates the raw Host header, including its optional port."""
        hosts = self.allowed_host_list
        return [value for host in hosts for value in (host, f"{host}:*")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
