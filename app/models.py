"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, TypeVar

from sqlalchemy import DateTime, Dialect, Float, ForeignKey, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.state_machine import CourierStatus, OrderStatus

E = TypeVar("E", OrderStatus, CourierStatus)


class _StrEnumType(TypeDecorator[E], Generic[E]):
    """Persist a str-based ``Enum`` by value and restore it as the enum member."""

    impl = String(32)
    cache_ok = True

    def __init__(self, enum_cls: type[E]) -> None:
        self._enum_cls: type[E] = enum_cls
        super().__init__()

    def process_bind_param(self, value: E | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(self._enum_cls(value).value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> E | None:
        if value is None:
            return None
        return self._enum_cls(value)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Courier(Base):
    """A courier that can be assigned orders."""

    __tablename__ = "couriers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    status: Mapped[CourierStatus] = mapped_column(
        _StrEnumType(CourierStatus), default=CourierStatus.AVAILABLE
    )
    current_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Order(Base):
    """A delivery order and its dispatch state."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[OrderStatus] = mapped_column(
        _StrEnumType(OrderStatus), default=OrderStatus.PENDING, index=True
    )

    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lon: Mapped[float] = mapped_column(Float)
    dropoff_lat: Mapped[float] = mapped_column(Float)
    dropoff_lon: Mapped[float] = mapped_column(Float)

    courier_id: Mapped[str | None] = mapped_column(ForeignKey("couriers.id"), nullable=True)
    courier: Mapped[Courier | None] = relationship("Courier", foreign_keys=[courier_id])

    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    eta_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
