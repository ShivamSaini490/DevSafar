
import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services.cleanup_service import CleanupCounts, CleanupService

logger = logging.getLogger(__name__)


async def run_cleanup_once(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    batch_size: int,
    price_history_retention_days: int = 180,
) -> CleanupCounts:
    async with session_factory() as session:
        counts = await CleanupService(session, redis=redis).delete_expired_conversations(
            batch_size=batch_size
        )
        history_count = await CleanupService(session, redis=redis).delete_expired_price_history(
            retention_days=price_history_retention_days
        )
        counts = CleanupCounts(
            conversations=counts.conversations,
            messages=counts.messages,
            trips=counts.trips,
            itineraries=counts.itineraries,
            redis_streams=counts.redis_streams,
            price_history=history_count,
        )
    logger.info(
        "Expired conversation cleanup completed",
        extra={
            "deleted_conversations": counts.conversations,
            "deleted_messages": counts.messages,
            "deleted_trips": counts.trips,
            "deleted_itineraries": counts.itineraries,
            "deleted_redis_streams": counts.redis_streams,
            "deleted_price_history": counts.price_history,
        },
    )
    return counts


async def run_cleanup_loop(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
) -> None:
    while True:
        try:
            await run_cleanup_once(
                session_factory,
                redis,
                batch_size=settings.cleanup_batch_size,
                price_history_retention_days=settings.price_history_retention_days,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Expired conversation cleanup failed")
        await asyncio.sleep(settings.cleanup_interval_seconds)
