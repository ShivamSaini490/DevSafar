from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.dependencies import postgres_is_ready, redis_is_ready
from app.core.exceptions import ServiceUnavailableError

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessChecks(BaseModel):
    postgres: bool
    redis: bool


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    checks: ReadinessChecks


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(
    postgres: Annotated[bool, Depends(postgres_is_ready)],
    redis: Annotated[bool, Depends(redis_is_ready)],
) -> ReadinessResponse:
    checks = ReadinessChecks(postgres=postgres, redis=redis)
    if not postgres or not redis:
        raise ServiceUnavailableError(details={"checks": checks.model_dump()})
    return ReadinessResponse(status="ready", checks=checks)
