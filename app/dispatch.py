"""Dispatch logic: assignment, queueing, and lifecycle transitions.

This module is the single place order state changes. All mutations go through
:meth:`DispatchService.transition`, which enforces the state machine, keeps the
courier/order relationship consistent, publishes events, and refreshes metrics.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.events import EventBus, event_bus
from app.geo import eta_minutes, haversine_km
from app.logging_config import get_logger
from app.metrics import (
    assignments_total,
    dispatch_latency_seconds,
    orders_created_total,
    set_status_counts,
)
from app.models import Courier, Order
from app.schemas import OrderCreate
from app.state_machine import (
    CourierStatus,
    InvalidTransitionError,
    OrderStatus,
    assert_transition,
)

logger = get_logger("dispatch")


class DispatchError(Exception):
    """Base class for dispatch errors."""


class OrderNotFoundError(DispatchError):
    """Raised when an order id does not exist."""


class CourierBusyError(DispatchError):
    """Raised when a busy courier's availability is changed out from under an order."""


class DispatchService:
    """Coordinates assignment, queueing and lifecycle transitions."""

    def __init__(
        self,
        settings: Settings | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bus = bus or event_bus

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    def _publish(self, order: Order, previous: OrderStatus | None) -> None:
        event: dict[str, Any] = {
            "type": "order_status",
            "order_id": order.id,
            "status": order.status.value,
            "previous_status": previous.value if previous is not None else None,
            "courier_id": order.courier_id,
            "eta_minutes": order.eta_minutes,
        }
        self.bus.publish(event)

    def refresh_metrics(self, session: Session) -> None:
        """Recompute the ``orders_by_status`` gauge from the database."""
        rows = session.execute(select(Order.status, func.count()).group_by(Order.status)).all()
        counts: dict[OrderStatus, int] = dict(rows)
        set_status_counts(counts)

    # -- transitions -------------------------------------------------------

    def transition(self, session: Session, order: Order, target: OrderStatus) -> Order:
        """Move ``order`` to ``target``, enforcing the state machine.

        Raises:
            InvalidTransitionError: if the transition is not allowed.
        """
        previous = order.status
        assert_transition(previous, target)
        order.status = target
        session.add(order)
        session.flush()
        session.commit()
        session.refresh(order)
        self.refresh_metrics(session)
        self._publish(order, previous)
        logger.info(
            "order transition",
            extra={
                "order_id": order.id,
                "from_status": previous.value,
                "to_status": target.value,
            },
        )
        return order

    # -- assignment --------------------------------------------------------

    def _nearest_available_courier(
        self, session: Session, order: Order
    ) -> tuple[Courier, float] | None:
        """Return the nearest available courier within radius, with distance."""
        couriers = (
            session.execute(select(Courier).where(Courier.status == CourierStatus.AVAILABLE))
            .scalars()
            .all()
        )
        best: tuple[Courier, float] | None = None
        for courier in couriers:
            distance = haversine_km(courier.lat, courier.lon, order.pickup_lat, order.pickup_lon)
            if distance > self.settings.assignment_radius_km:
                continue
            if best is None or distance < best[1]:
                best = (courier, distance)
        return best

    def try_assign(self, session: Session, order: Order) -> bool:
        """Attempt to assign a courier to ``order``.

        Returns ``True`` if an assignment was made. The courier claim is done
        with a conditional ``UPDATE`` guarded on the courier still being
        available, so two concurrent dispatchers can never grab the same
        courier. Timed for the dispatch-latency metric.
        """
        if order.status not in (OrderStatus.PENDING, OrderStatus.QUEUED):
            return False

        start = time.perf_counter()
        try:
            while True:
                candidate = self._nearest_available_courier(session, order)
                if candidate is None:
                    return False
                courier, distance = candidate

                # Atomic claim: only succeeds if the courier is still available.
                result = cast(
                    "CursorResult[Any]",
                    session.execute(
                        update(Courier)
                        .where(
                            Courier.id == courier.id,
                            Courier.status == CourierStatus.AVAILABLE,
                        )
                        .values(status=CourierStatus.BUSY, current_order_id=order.id)
                    ),
                )
                if result.rowcount != 1:
                    # Lost the race; drop this session's stale view and retry.
                    session.rollback()
                    continue

                previous = order.status
                order.courier_id = courier.id
                order.status = OrderStatus.ASSIGNED
                order.distance_km = distance
                order.eta_minutes = eta_minutes(distance, self.settings.courier_speed_kmh)
                session.add(order)
                session.commit()
                session.refresh(order)
                assignments_total.inc()
                self.refresh_metrics(session)
                self._publish(order, previous)
                logger.info(
                    "order assigned",
                    extra={
                        "order_id": order.id,
                        "courier_id": courier.id,
                        "distance_km": round(distance, 3),
                    },
                )
                return True
        finally:
            dispatch_latency_seconds.observe(time.perf_counter() - start)

    # -- public operations -------------------------------------------------

    def create_order(
        self,
        session: Session,
        data: OrderCreate,
        idempotency_key: str | None = None,
    ) -> tuple[Order, bool]:
        """Create an order and dispatch it.

        Returns ``(order, created)`` where ``created`` is ``False`` if an
        existing order was returned for a repeated idempotency key.
        """
        if idempotency_key is not None:
            existing = session.execute(
                select(Order).where(Order.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if existing is not None:
                return existing, False

        order = Order(
            id=self._new_id(),
            status=OrderStatus.PENDING,
            pickup_lat=data.pickup_lat,
            pickup_lon=data.pickup_lon,
            dropoff_lat=data.dropoff_lat,
            dropoff_lon=data.dropoff_lon,
            idempotency_key=idempotency_key,
        )
        session.add(order)
        try:
            session.commit()
        except IntegrityError:
            # Concurrent request with the same idempotency key won the insert.
            session.rollback()
            if idempotency_key is None:
                raise
            existing = session.execute(
                select(Order).where(Order.idempotency_key == idempotency_key)
            ).scalar_one()
            return existing, False

        session.refresh(order)
        orders_created_total.inc()
        self.refresh_metrics(session)
        self._publish(order, None)

        assigned = self.try_assign(session, order)
        if not assigned:
            self.transition(session, order, OrderStatus.QUEUED)
        return order, True

    def _pop_next_queued(self, session: Session) -> Order | None:
        """Return the oldest queued order, if any."""
        return (
            session.execute(
                select(Order)
                .where(Order.status == OrderStatus.QUEUED)
                .order_by(Order.created_at.asc(), Order.id.asc())
            )
            .scalars()
            .first()
        )

    def process_queue(self, session: Session) -> int:
        """Assign as many queued orders as there are free couriers.

        Returns the number of orders assigned.
        """
        assigned_count = 0
        while True:
            order = self._pop_next_queued(session)
            if order is None:
                break
            if not self.try_assign(session, order):
                break
            assigned_count += 1
        return assigned_count

    def release_courier(self, session: Session, courier: Courier) -> None:
        """Mark a courier available and drain the queue."""
        session.execute(
            update(Courier)
            .where(Courier.id == courier.id)
            .values(status=CourierStatus.AVAILABLE, current_order_id=None)
        )
        session.commit()
        self.process_queue(session)

    def update_courier(
        self,
        session: Session,
        courier: Courier,
        *,
        lat: float | None = None,
        lon: float | None = None,
        status: CourierStatus | None = None,
    ) -> Courier:
        """Update a courier's location and/or availability.

        ``status`` may only be set to ``available`` or ``offline`` and not while
        the courier is mid-delivery (``busy``). Any change that could make the
        courier eligible — moving, or coming back online — drains the queue.

        Raises:
            CourierBusyError: if an availability change is attempted while busy.
        """
        if status is not None and status not in (
            CourierStatus.AVAILABLE,
            CourierStatus.OFFLINE,
        ):
            raise ValueError("status may only be set to 'available' or 'offline'")

        changing_status = status is not None and status != courier.status
        if changing_status and courier.status == CourierStatus.BUSY:
            raise CourierBusyError(courier.id)

        if lat is not None:
            courier.lat = lat
        if lon is not None:
            courier.lon = lon
        if status is not None:
            courier.status = status

        session.add(courier)
        session.commit()
        session.refresh(courier)

        # Moving or coming online may let queued orders be assigned.
        if courier.status == CourierStatus.AVAILABLE:
            self.process_queue(session)
            session.refresh(courier)
        return courier

    def advance_order(self, session: Session, order: Order, target: OrderStatus) -> Order:
        """Drive an order to ``target`` and handle courier side effects.

        Terminal transitions (``delivered``/``cancelled``) free the assigned
        courier and trigger queue processing.
        """
        order = self.transition(session, order, target)
        is_terminal = target in (OrderStatus.DELIVERED, OrderStatus.CANCELLED)
        if is_terminal and order.courier_id is not None:
            courier = session.get(Courier, order.courier_id)
            freed_order_id = order.id
            order.courier_id = None
            session.add(order)
            session.commit()
            if courier is not None and courier.current_order_id == freed_order_id:
                self.release_courier(session, courier)
        return order


def get_order_or_raise(session: Session, order_id: str) -> Order:
    """Fetch an order by id or raise :class:`OrderNotFoundError`."""
    order = session.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(order_id)
    return order


__all__ = [
    "DispatchService",
    "DispatchError",
    "OrderNotFoundError",
    "CourierBusyError",
    "InvalidTransitionError",
    "get_order_or_raise",
]
