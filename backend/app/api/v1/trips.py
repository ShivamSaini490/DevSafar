
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import AuthContext, get_auth_context, get_db_session
from app.schemas.trip import TripResponse
from app.services.trip_service import TripService

router = APIRouter(prefix="/trips", tags=["trips"])


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(
    trip_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TripResponse:
    return await TripService(db).get_owned_active(
        trip_id=trip_id, owner_id=context.user.id
    )
