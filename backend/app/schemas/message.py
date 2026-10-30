
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_content(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Message content cannot be blank")
    return cleaned


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    _validate_content = field_validator("content")(_clean_content)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MessageTurnResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse


class TemporaryChatRequest(BaseModel):
    temp_session_id: str = Field(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    temp_token: str | None = Field(
        default=None,
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    content: str = Field(min_length=1, max_length=4000)

    _validate_content = field_validator("content")(_clean_content)


class TemporaryChatResponse(BaseModel):
    assistant_message: str
    temp_token: str | None
    context_message_count: int
    expires_in_seconds: int
