"""Tests for idempotency-key handling on order creation."""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dispatch import DispatchService
from app.schemas import OrderCreate
from tests.conftest import add_courier

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.01, dropoff_lon=0.01)


def test_same_key_returns_same_order(session: Session, service: DispatchService) -> None:
    first, created1 = service.create_order(session, NEAR, idempotency_key="abc")
    second, created2 = service.create_order(session, NEAR, idempotency_key="abc")
    assert created1 is True
    assert created2 is False
    assert first.id == second.id


def test_same_key_does_not_create_duplicate(session: Session, service: DispatchService) -> None:
    from app.models import Order

    service.create_order(session, NEAR, idempotency_key="k1")
    service.create_order(session, NEAR, idempotency_key="k1")
    service.create_order(session, NEAR, idempotency_key="k1")
    assert session.query(Order).count() == 1


def test_different_keys_create_different_orders(session: Session, service: DispatchService) -> None:
    first, _ = service.create_order(session, NEAR, idempotency_key="a")
    second, _ = service.create_order(session, NEAR, idempotency_key="b")
    assert first.id != second.id


def test_no_key_always_creates(session: Session, service: DispatchService) -> None:
    first, c1 = service.create_order(session, NEAR)
    second, c2 = service.create_order(session, NEAR)
    assert c1 is True and c2 is True
    assert first.id != second.id


def test_repeat_returns_assignment_state(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    first, _ = service.create_order(session, NEAR, idempotency_key="z")
    assert first.status.value == "assigned"
    second, created = service.create_order(session, NEAR, idempotency_key="z")
    assert created is False
    assert second.courier_id == first.courier_id


def test_concurrent_same_key_creates_one_order() -> None:
    """Two parallel requests with the same key must yield a single order."""
    from app.models import Order

    results: list[str] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        svc = DispatchService()
        db = SessionLocal()
        try:
            barrier.wait()
            order, _ = svc.create_order(db, NEAR, idempotency_key="race")
            results.append(order.id)
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(set(results)) == 1

    verify = SessionLocal()
    try:
        assert verify.query(Order).filter(Order.idempotency_key == "race").count() == 1
    finally:
        verify.close()
