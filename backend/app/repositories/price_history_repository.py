from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_history import PriceHistory


@dataclass(frozen=True, slots=True)
class PriceHistoryWrite:
    context: str
    mode: str
    origin_code: str | None
    destination_code: str
    travel_date: date
    observed_at: datetime
    booking_bucket: str
    price: Decimal
    currency: str
    provider: str
    price_unit: str
    cabin_or_class: str
    passengers: int
    nights: int | None
    is_demo: bool
    expires_at: datetime


class PriceHistoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, item: PriceHistoryWrite) -> PriceHistory:
        if item.currency != "INR":
            raise ValueError("Price history accepts INR only")
        if item.price <= 0:
            raise ValueError("Price history accepts positive prices only")
        row = PriceHistory(**asdict(item))
        self.db.add(row)
        await self.db.flush()
        return row

    async def comparable(
        self,
        *,
        context: str,
        booking_bucket: str,
        observed_after: datetime,
        now: datetime,
        allow_demo: bool,
        limit: int = 100,
    ) -> list[PriceHistory]:
        statement = (
            select(PriceHistory)
            .where(
                PriceHistory.context == context,
                PriceHistory.booking_bucket == booking_bucket,
                PriceHistory.currency == "INR",
                PriceHistory.observed_at >= observed_after,
                PriceHistory.expires_at > now,
            )
            .order_by(PriceHistory.observed_at.desc(), PriceHistory.id.desc())
            .limit(limit)
        )
        if not allow_demo:
            statement = statement.where(PriceHistory.is_demo.is_(False))
        return list((await self.db.scalars(statement)).all())

    async def delete_expired(self, *, now: datetime, retention_days: int) -> int:
        cutoff = now - timedelta(days=retention_days)
        result = await self.db.execute(
            delete(PriceHistory).where(
                (PriceHistory.observed_at < cutoff) | (PriceHistory.expires_at <= now)
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)
