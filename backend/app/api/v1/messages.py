import logging
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import TripPlanner, TripPlanningFailure
from app.agents.llm import intent_failure_log_fields
from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_auth_context,
    get_db_session,
    get_redis_client,
    get_request_settings,
    get_trip_planner,
    require_csrf,
)
from app.core.exceptions import AppError
from app.core.rate_limiter import PlanningAdmissionService
from app.schemas.message import (
    AsyncPlanningResponse,
    MessageCreateRequest,
    MessageResponse,
    MessageTurnResponse,
)
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.planning_service import AsyncPlanningService, PlanningStreamStore

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["messages"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=MessageTurnResponse | AsyncPlanningResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    planner: Annotated[TripPlanner, Depends(get_trip_planner)],
    async_mode: Annotated[bool, Query(alias="async")] = False,
) -> MessageTurnResponse | AsyncPlanningResponse:
    owner_id = context.user.id
    await ConversationService(db).get_required(
        conversation_id=conversation_id,
        owner_id=owner_id,
    )
    await db.rollback()
    lease = await PlanningAdmissionService(redis, settings).admit_saved(owner_id)
    service = ChatService(db, planner)
    try:
        if async_mode:
            trip_id = uuid4()
            prepared = await service.begin_async_turn(
                conversation_id=conversation_id,
                owner_id=owner_id,
                content=payload.content,
            )
            streams = PlanningStreamStore(redis, settings)
            await streams.create_saved(
                trip_id=trip_id,
                conversation_id=conversation_id,
                owner_id=owner_id,
            )
            planning = AsyncPlanningService(
                redis=redis,
                settings=settings,
                planner=planner,
                session_factory=request.app.state.db_session_factory,
            )
            background_tasks.add_task(
                planning.run_saved,
                trip_id=trip_id,
                conversation_id=conversation_id,
                owner_id=owner_id,
                content=payload.content,
                previous_trip=prepared.previous_trip,
                lease=lease,
                request_id=getattr(request.state, "request_id", "unavailable"),
            )
            response.status_code = status.HTTP_202_ACCEPTED
            return AsyncPlanningResponse(
                user_message=MessageResponse.model_validate(prepared.user_message),
                trip_id=trip_id,
                events_url=f"/api/v1/trips/{trip_id}/events",
            )
        turn = await service.append_turn(
            conversation_id=conversation_id,
            owner_id=owner_id,
            content=payload.content,
        )
    except TripPlanningFailure as exc:
        await db.rollback()
        logger.warning(
            "Trip planning request failed",
            extra={
                "request_id": getattr(request.state, "request_id", "unavailable"),
                **intent_failure_log_fields(exc),
            },
        )
        raise AppError(
            503,
            exc.code,
            exc.public_message,
        ) from exc
    except Exception:
        if async_mode:
            await lease.release()
        raise
    finally:
        if not async_mode:
            await lease.release()
    return MessageTurnResponse(
        user_message=MessageResponse.model_validate(turn.user_message),
        assistant_message=MessageResponse.model_validate(turn.assistant_message),
        trip=turn.trip,
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
