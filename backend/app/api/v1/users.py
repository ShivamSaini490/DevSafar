from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_auth_context,
    get_db_session,
    get_request_settings,
    require_csrf,
)
from app.schemas.user import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    MessageResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def me(context: Annotated[AuthContext, Depends(get_auth_context)]) -> UserResponse:
    return UserResponse.model_validate(context.user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserResponse:
    user = await UserService(db).update(context.user, name=payload.name, email=payload.email)
    return UserResponse.model_validate(user)


@router.post("/me/change-password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> MessageResponse:
    await UserService(db).change_password(
        context.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    response.delete_cookie(settings.access_token_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return MessageResponse(message="Password changed. Please log in again.")


@router.delete("/me", response_model=MessageResponse)
async def delete_me(
    payload: DeleteAccountRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> MessageResponse:
    await UserService(db).delete_account(context.user, password=payload.password)
    response.delete_cookie(settings.access_token_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return MessageResponse(message="Account deleted.")
