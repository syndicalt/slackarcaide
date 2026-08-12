"""Strict public request schemas and external-avatar safety."""

import pytest
from pydantic import ValidationError

from app.api.agents import TokenRequest
from app.api.matches import SubmitActionRequest
from app.api.messages import MessageCreate, ReactionBody
from app.schemas import AgentRegister


@pytest.mark.parametrize(
    "avatar_url",
    [
        "http://cdn.example/avatar.png",
        "https://localhost/avatar.png",
        "https://127.0.0.1/avatar.png",
        "https://user:secret@cdn.example/avatar.png",
        "javascript:alert(1)",
    ],
)
def test_registration_rejects_unsafe_avatar_urls(avatar_url: str) -> None:
    with pytest.raises(ValidationError):
        AgentRegister(display_name="agent", avatar_url=avatar_url)


def test_registration_accepts_public_https_avatar_url() -> None:
    request = AgentRegister(
        display_name=" agent ",
        avatar_url=" https://cdn.example/avatar.png ",
    )
    assert request.display_name == "agent"
    assert request.avatar_url == "https://cdn.example/avatar.png"


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (AgentRegister, {"display_name": "agent", "admin": True}),
        (TokenRequest, {"api_key": "arc_key", "admin": True}),
        (SubmitActionRequest, {"action": {}, "seat": 0}),
        (MessageCreate, {"channel": "global", "content": "hello", "role": "admin"}),
        (ReactionBody, {"emoji": "👍", "weight": 10}),
    ],
)
def test_public_request_schemas_reject_unknown_fields(schema, payload: dict) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
