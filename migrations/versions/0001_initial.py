"""initial schema: couriers and orders

Revision ID: 0001
Revises:
Create Date: 2026-10-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "couriers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_order_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lon", sa.Float(), nullable=False),
        sa.Column("dropoff_lat", sa.Float(), nullable=False),
        sa.Column("dropoff_lon", sa.Float(), nullable=False),
        sa.Column("courier_id", sa.String(length=36), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("eta_minutes", sa.Float(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["courier_id"], ["couriers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_table("orders")
    op.drop_table("couriers")
