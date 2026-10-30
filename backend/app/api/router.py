from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.health import router as health_router
from app.api.v1.messages import router as messages_router
from app.api.v1.otp import router as otp_router
from app.api.v1.temporary_chat import router as temporary_chat_router
from app.api.v1.trips import router as trips_router
from app.api.v1.users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(otp_router)
api_router.include_router(users_router)
api_router.include_router(conversations_router)
api_router.include_router(messages_router)
api_router.include_router(temporary_chat_router)
api_router.include_router(trips_router)
