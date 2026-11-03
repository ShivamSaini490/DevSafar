"""Add anonymized provider price history.

Revision ID: 0004_price_history
Revises: 0003_langgraph_vertical_slice
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_price_history"
down_revision: str | None = "0003_langgraph_vertical_slice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("context", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("origin_code", sa.String(length=20), nullable=True),
        sa.Column("destination_code", sa.String(length=200), nullable=False),
        sa.Column("travel_date", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("booking_bucket", sa.String(length=20), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("price_unit", sa.String(length=100), nullable=False),
        sa.Column("cabin_or_class", sa.String(length=50), nullable=False),
        sa.Column("passengers", sa.Integer(), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency = 'INR'", name="ck_price_history_price_history_inr_only"),
        sa.CheckConstraint("price > 0", name="ck_price_history_price_positive"),
        sa.CheckConstraint(
            "booking_bucket IN ('same_day', '1_7_days', '8_30_days', '31_plus')",
            name="ck_price_history_price_history_booking_bucket",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_price_history"),
    )
    op.create_index(
        "ix_price_history_context_bucket_observed",
        "price_history",
        ["context", "booking_bucket", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("price_history")
