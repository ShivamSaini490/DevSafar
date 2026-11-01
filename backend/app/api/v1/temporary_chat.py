import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from redis.asyncio import Redis

from app.agents.graph import TripPlanner, TripPlanningFailure
from app.agents.llm import intent_failure_log_fields
from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_redis_client,
    get_request_settings,
    get_trip_planner,
    require_csrf_if_authenticated,
)
from app.core.exceptions import AppError
from app.core.rate_limiter import PlanningAdmissionService
from app.schemas.message import (
    TemporaryAsyncPlanningResponse,
    TemporaryChatRequest,
    TemporaryChatResponse,
)
from app.services.planning_service import AsyncPlanningService, PlanningStreamStore
from app.services.temporary_chat_service import TemporaryChatService

router = APIRouter(prefix="/chat", tags=["temporary-chat"])
logger = logging.getLogger(__name__)


@router.post(
    "/temporary",
    response_model=TemporaryChatResponse | TemporaryAsyncPlanningResponse,
)
async def temporary_chat(
    payload: TemporaryChatRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    _context: Annotated[AuthContext | None, Depends(require_csrf_if_authenticated)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    planner: Annotated[TripPlanner, Depends(get_trip_planner)],
    async_mode: Annotated[bool, Query(alias="async")] = False,
) -> TemporaryChatResponse | TemporaryAsyncPlanningResponse:
    service = TemporaryChatService(redis, settings, planner)
    await service.enforce_limits(
        client_ip=request.client.host if request.client else "unknown",
        temp_session_id=payload.temp_session_id,
    )
    prepared = await service.prepare_turn(
        temp_session_id=payload.temp_session_id,
        temp_token=payload.temp_token,
    )
    lease = await PlanningAdmissionService(redis, settings).admit_temporary(
        client_ip=request.client.host if request.client else "unknown",
        temp_session_id=payload.temp_session_id,
    )
    try:
        if async_mode:
            trip_id = uuid4()
            streams = PlanningStreamStore(redis, settings)
            await streams.create_temporary(
                trip_id=trip_id,
                temp_session_id=payload.temp_session_id,
                temp_token=prepared.token,
            )
            planning = AsyncPlanningService(
                redis=redis,
                settings=settings,
                planner=planner,
                session_factory=request.app.state.db_session_factory,
            )
            background_tasks.add_task(
                planning.run_temporary,
                trip_id=trip_id,
                temp_session_id=payload.temp_session_id,
                content=payload.content,
                prepared=prepared,
                lease=lease,
                request_id=getattr(request.state, "request_id", "unavailable"),
            )
            response.status_code = status.HTTP_202_ACCEPTED
            return TemporaryAsyncPlanningResponse(
                temp_token=prepared.issued_token,
                trip_id=trip_id,
                events_url=f"/api/v1/trips/{trip_id}/events",
            )
        turn = await service.run_prepared(
            temp_session_id=payload.temp_session_id,
            content=payload.content,
            prepared=prepared,
        )
    except TripPlanningFailure as exc:
        logger.warning(
            "Temporary trip planning request failed",
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
    return TemporaryChatResponse(
        assistant_message=turn.assistant_message,
        temp_token=turn.issued_token,
        context_message_count=turn.context_message_count,
        expires_in_seconds=settings.temporary_chat_ttl_seconds,
        trip=turn.trip,
    )
