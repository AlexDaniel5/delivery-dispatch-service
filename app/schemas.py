"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.state_machine import CourierStatus, OrderStatus

T = TypeVar("T")


class CourierCreate(BaseModel):
    """Payload for registering a courier."""

    name: str = Field(min_length=1, max_length=255)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class CourierRead(BaseModel):
    """Courier representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    lat: float
    lon: float
    status: CourierStatus
    current_order_id: str | None


class CourierUpdate(BaseModel):
    """Partial update for a courier's location and/or availability."""

    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    status: CourierStatus | None = None

    @field_validator("status")
    @classmethod
    def _status_is_manually_settable(cls, value: CourierStatus | None) -> CourierStatus | None:
        if value is not None and value not in (
            CourierStatus.AVAILABLE,
            CourierStatus.OFFLINE,
        ):
            raise ValueError("status may only be set to 'available' or 'offline'")
        return value


class OrderCreate(BaseModel):
    """Payload for creating an order."""

    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lon: float = Field(ge=-180, le=180)
    dropoff_lat: float = Field(ge=-90, le=90)
    dropoff_lon: float = Field(ge=-180, le=180)


class OrderRead(BaseModel):
    """Order representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: OrderStatus
    pickup_lat: float
    pickup_lon: float
    dropoff_lat: float
    dropoff_lon: float
    courier_id: str | None
    distance_km: float | None
    eta_minutes: float | None
    created_at: datetime
    updated_at: datetime


class OrderStatusUpdate(BaseModel):
    """Payload to drive an order to a new status."""

    status: OrderStatus


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    detail: str


class Page(BaseModel, Generic[T]):
    """A paginated list response."""

    items: list[T]
    total: int
    limit: int
    offset: int
