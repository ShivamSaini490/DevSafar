from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.trip import TripResponse


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
    trip: TripResponse


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
    trip: TripResponse


class AsyncPlanningResponse(BaseModel):
    user_message: MessageResponse
    trip_id: UUID
    status: Literal["running"] = "running"
    events_url: str


class TemporaryAsyncPlanningResponse(BaseModel):
    temp_token: str | None = None
    trip_id: UUID
    status: Literal["running"] = "running"
    events_url: str
