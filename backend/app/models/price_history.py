from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("currency = 'INR'", name="price_history_inr_only"),
        CheckConstraint(
            "booking_bucket IN ('same_day', '1_7_days', '8_30_days', '31_plus')",
            name="price_history_booking_bucket",
        ),
        Index(
            "ix_price_history_context_bucket_observed",
            "context",
            "booking_bucket",
            "observed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    context: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(20))
    origin_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    destination_code: Mapped[str] = mapped_column(String(200))
    travel_date: Mapped[date] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    booking_bucket: Mapped[str] = mapped_column(String(20))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    provider: Mapped[str] = mapped_column(String(100))
    price_unit: Mapped[str] = mapped_column(String(100))
    cabin_or_class: Mapped[str] = mapped_column(String(50))
    passengers: Mapped[int] = mapped_column(Integer)
    nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
