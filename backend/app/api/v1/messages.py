
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import AuthContext, get_auth_context, get_db_session, require_csrf
from app.schemas.message import MessageCreateRequest, MessageResponse, MessageTurnResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["messages"])


@router.post("", response_model=MessageTurnResponse, status_code=status.HTTP_201_CREATED)
async def post_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MessageTurnResponse:
    turn = await ChatService(db).append_placeholder_turn(
        conversation_id=conversation_id,
        owner_id=context.user.id,
        content=payload.content,
    )
    return MessageTurnResponse(
        user_message=MessageResponse.model_validate(turn.user_message),
        assistant_message=MessageResponse.model_validate(turn.assistant_message),
    )


@router.get("", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageResponse]:
    messages = await ChatService(db).list_messages(
        conversation_id=conversation_id,
        owner_id=context.user.id,
        limit=limit,
        offset=offset,
    )
    return [MessageResponse.model_validate(item) for item in messages]
