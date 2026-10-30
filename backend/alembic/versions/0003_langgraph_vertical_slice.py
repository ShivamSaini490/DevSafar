"""Create trips and versioned itineraries.

Revision ID: 0003_langgraph_vertical_slice
Revises: 0002_chat_modes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_langgraph_vertical_slice"
down_revision: str | None = "0002_chat_modes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('needs_clarification', 'completed', 'failed')",
            name=op.f("ck_trips_trip_status"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_trips_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trips")),
    )
    op.create_index(op.f("ix_trips_conversation_id"), "trips", ["conversation_id"])
    op.create_index(op.f("ix_trips_status"), "trips", ["status"])
    op.create_index(op.f("ix_trips_created_at"), "trips", ["created_at"])
    op.create_table(
        "itineraries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("itinerary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_itineraries_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["trips.id"],
            name=op.f("fk_itineraries_trip_id_trips"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_itineraries")),
        sa.UniqueConstraint(
            "conversation_id",
            "version",
            name="uq_itineraries_conversation_version",
        ),
    )
    op.create_index(
        op.f("ix_itineraries_conversation_id"), "itineraries", ["conversation_id"]
    )
    op.create_index(op.f("ix_itineraries_trip_id"), "itineraries", ["trip_id"])
    op.create_index(op.f("ix_itineraries_created_at"), "itineraries", ["created_at"])


def downgrade() -> None:
    op.drop_table("itineraries")
    op.drop_table("trips")
