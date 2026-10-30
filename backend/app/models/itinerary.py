
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.trip import Trip


class Itinerary(Base):
    __tablename__ = "itineraries"
    __table_args__ = (
        UniqueConstraint("conversation_id", "version", name="uq_itineraries_conversation_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    trip_id: Mapped[UUID] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    itinerary_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    trip: Mapped["Trip"] = relationship(back_populates="itineraries")
    conversation: Mapped["Conversation"] = relationship(back_populates="itineraries")
