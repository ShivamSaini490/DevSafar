
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import DEFAULT_CONVERSATION_TITLE


def _clean_title(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Title cannot be blank")
    return cleaned


class ConversationCreateRequest(BaseModel):
    title: str = Field(default=DEFAULT_CONVERSATION_TITLE, max_length=200)

    _validate_title = field_validator("title")(_clean_title)


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    _validate_title = field_validator("title")(_clean_title)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    created_at: datetime
    expires_at: datetime
