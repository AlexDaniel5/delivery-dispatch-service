"""Tests for the no-double-assignment guarantee (conditional UPDATE)."""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dispatch import DispatchService
from app.models import Courier, Order
from app.schemas import OrderCreate
from app.state_machine import CourierStatus, OrderStatus
from tests.conftest import add_courier, add_order

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.01, dropoff_lon=0.01)


def test_single_courier_two_orders_one_assigned(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    first, _ = service.create_order(session, NEAR)
    second, _ = service.create_order(session, NEAR)

    statuses = {first.status, second.status}
    assert statuses == {OrderStatus.ASSIGNED, OrderStatus.QUEUED}


def test_try_assign_twice_second_is_noop(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    o1 = add_order(session, order_id="o1")
    o2 = add_order(session, order_id="o2")

    assert service.try_assign(session, o1) is True
    # Courier now busy; the second order cannot claim it.
    assert service.try_assign(session, o2) is False

    session.refresh(o2)
    assert o2.status == OrderStatus.PENDING
    assert o2.courier_id is None


def test_courier_never_holds_two_orders(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    service.create_order(session, NEAR)
    service.create_order(session, NEAR)

    # Exactly one order references the courier.
    holders = session.query(Order).filter(Order.courier_id == "c1").count()
    assert holders == 1


def test_conditional_update_guard_is_status_based(
    session: Session, service: DispatchService
) -> None:
    # Pre-mark the courier busy; assignment must not override it.
    add_courier(session, lat=0.0, lon=0.0, status=CourierStatus.BUSY)
    order = add_order(session)
    assert service.try_assign(session, order) is False


def test_concurrent_assignment_single_courier() -> None:
    """Two threads dispatching two orders against one courier.

    The conditional UPDATE must ensure exactly one order is assigned and the
    courier is never double-booked.
    """
    setup = SessionLocal()
    try:
        add_courier(setup, courier_id="solo", lat=0.0, lon=0.0)
        add_order(setup, order_id="oa")
        add_order(setup, order_id="ob")
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    outcomes: dict[str, bool] = {}
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(order_id: str) -> None:
        svc = DispatchService()
        db = SessionLocal()
        try:
            order = db.get(Order, order_id)
            assert order is not None
            barrier.wait()
            assigned = svc.try_assign(db, order)
            with lock:
                outcomes[order_id] = assigned
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("oa",)),
        threading.Thread(target=worker, args=("ob",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    # Exactly one assignment succeeded.
    assert sum(outcomes.values()) == 1

    verify = SessionLocal()
    try:
        courier = verify.get(Courier, "solo")
        assert courier is not None
        assert courier.status == CourierStatus.BUSY
        assigned_orders = verify.query(Order).filter(Order.courier_id == "solo").count()
        assert assigned_orders == 1
    finally:
        verify.close()


def test_many_orders_one_courier_only_one_assigned(
    session: Session, service: DispatchService
) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    for _ in range(10):
        service.create_order(session, NEAR)
    assigned = session.query(Order).filter(Order.status == OrderStatus.ASSIGNED).count()
    queued = session.query(Order).filter(Order.status == OrderStatus.QUEUED).count()
    assert assigned == 1
    assert queued == 9
