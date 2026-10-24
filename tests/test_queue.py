"""Tests for queueing orders and draining the queue when couriers free up."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.dispatch import DispatchService
from app.models import Courier
from app.schemas import OrderCreate
from app.state_machine import CourierStatus, OrderStatus
from tests.conftest import add_courier

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.01, dropoff_lon=0.01)


def test_order_queued_when_no_courier(session: Session, service: DispatchService) -> None:
    order, _ = service.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED
    assert order.courier_id is None


def test_queued_order_assigned_when_courier_registered(
    session: Session, service: DispatchService
) -> None:
    order, _ = service.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED

    add_courier(session, lat=0.0, lon=0.0)
    assigned = service.process_queue(session)
    assert assigned == 1

    session.refresh(order)
    assert order.status == OrderStatus.ASSIGNED
    assert order.courier_id == "c1"


def test_queue_assigned_in_fifo_order(session: Session, service: DispatchService) -> None:
    first, _ = service.create_order(session, NEAR)
    second, _ = service.create_order(session, NEAR)
    assert first.status == OrderStatus.QUEUED
    assert second.status == OrderStatus.QUEUED

    # Only one courier: the first queued order wins.
    add_courier(session, lat=0.0, lon=0.0)
    service.process_queue(session)

    session.refresh(first)
    session.refresh(second)
    assert first.status == OrderStatus.ASSIGNED
    assert second.status == OrderStatus.QUEUED


def test_process_queue_assigns_multiple(session: Session, service: DispatchService) -> None:
    o1, _ = service.create_order(session, NEAR)
    o2, _ = service.create_order(session, NEAR)
    add_courier(session, courier_id="c1", lat=0.0, lon=0.0)
    add_courier(session, courier_id="c2", lat=0.0, lon=0.0)

    assigned = service.process_queue(session)
    assert assigned == 2
    session.refresh(o1)
    session.refresh(o2)
    assert o1.status == OrderStatus.ASSIGNED
    assert o2.status == OrderStatus.ASSIGNED
    assert {o1.courier_id, o2.courier_id} == {"c1", "c2"}


def test_process_queue_stops_when_no_couriers(session: Session, service: DispatchService) -> None:
    service.create_order(session, NEAR)
    service.create_order(session, NEAR)
    add_courier(session, lat=0.0, lon=0.0)
    assigned = service.process_queue(session)
    assert assigned == 1  # only one courier available


def test_delivery_frees_courier_and_assigns_queued(
    session: Session, service: DispatchService
) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    first, _ = service.create_order(session, NEAR)
    assert first.status == OrderStatus.ASSIGNED

    second, _ = service.create_order(session, NEAR)
    assert second.status == OrderStatus.QUEUED

    # Deliver the first order; the freed courier should pick up the queued one.
    service.advance_order(session, first, OrderStatus.PICKED_UP)
    service.advance_order(session, first, OrderStatus.DELIVERED)

    session.refresh(second)
    assert second.status == OrderStatus.ASSIGNED
    assert second.courier_id == "c1"


def test_cancel_assigned_order_frees_courier(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    first, _ = service.create_order(session, NEAR)
    second, _ = service.create_order(session, NEAR)
    assert second.status == OrderStatus.QUEUED

    service.advance_order(session, first, OrderStatus.CANCELLED)

    session.refresh(second)
    assert second.status == OrderStatus.ASSIGNED


def test_released_courier_becomes_available(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0)
    order, _ = service.create_order(session, NEAR)
    service.advance_order(session, order, OrderStatus.CANCELLED)
    freed = session.get(Courier, courier.id)
    assert freed is not None
    assert freed.status == CourierStatus.AVAILABLE
    assert freed.current_order_id is None


def test_process_queue_no_op_when_empty(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    assert service.process_queue(session) == 0
