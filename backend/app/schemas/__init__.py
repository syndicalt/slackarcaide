"""Pydantic schemas: base + shared request/response shapes.

Feature agents add their own schemas here or in sibling modules. The Observation
object (spec 4.4) is defined in app/realtime/serializer once games exist.
"""
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


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

    display_name: _AgentName
    bio: str | None = Field(default=None, max_length=512)
    avatar_url: str | None = Field(default=None, max_length=512)


class MessagePublic(ORMModel):
    id: uuid.UUID
    channel: str
    author_id: uuid.UUID
    content: str
    tick_reference: int | None = None
    parent_id: uuid.UUID | None = None
    created_at: datetime | None = None
