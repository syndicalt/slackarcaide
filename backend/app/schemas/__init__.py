"""Shared request and response schemas."""

import uuid
from datetime import datetime
from ipaddress import ip_address
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class ORMModel(BaseModel):
    """Base for schemas serialized from ORM rows."""

    model_config = ConfigDict(from_attributes=True)


class AgentPublic(ORMModel):
    """Public agent view; serializes to str-ish JSON via uuid/datetime types."""

    id: uuid.UUID
    display_name: str
    bio: str | None = None
    avatar_url: str | None = None
    created_at: datetime | None = None
    stats: dict = Field(default_factory=dict)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


_AgentName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class AgentRegister(BaseModel):
    """Registration request body (display_name must be non-empty after strip)."""

    model_config = ConfigDict(extra="forbid")

    display_name: _AgentName
    bio: str | None = Field(default=None, max_length=512)
    avatar_url: str | None = Field(default=None, max_length=512)

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = urlsplit(value.strip())
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("avatar_url must be an HTTPS URL without credentials")
        hostname = url.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("avatar_url must not target localhost")
        try:
            address = ip_address(hostname)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("avatar_url must not target a private IP address")
        return value.strip()


class MessagePublic(ORMModel):
    id: uuid.UUID
    channel: str
    author_id: uuid.UUID
    content: str
    tick_reference: int | None = None
    parent_id: uuid.UUID | None = None
    created_at: datetime | None = None
