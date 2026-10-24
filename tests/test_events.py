"""Tests for the event bus and event publishing from dispatch."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.dispatch import DispatchService
from app.events import EventBus
from app.schemas import OrderCreate
from app.state_machine import OrderStatus
from tests.conftest import add_courier

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.01, dropoff_lon=0.01)


def _drain(bus: EventBus) -> list[dict[str, object]]:
    queue = bus.subscribe()
    events: list[dict[str, object]] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_subscribe_and_publish_inline() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    bus.publish({"type": "test", "n": 1})
    assert queue.get_nowait() == {"type": "test", "n": 1}


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    bus.publish({"type": "test"})
    assert queue.empty()
    assert bus.subscriber_count == 0


def test_fanout_to_multiple_subscribers() -> None:
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish({"type": "x"})
    assert q1.get_nowait() == {"type": "x"}
    assert q2.get_nowait() == {"type": "x"}


def test_create_order_publishes_status_events(
    session: Session, service: DispatchService, bus: EventBus
) -> None:
    queue = bus.subscribe()
    add_courier(session, lat=0.0, lon=0.0)
    order, _ = service.create_order(session, NEAR)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    statuses = [e["status"] for e in events]
    assert "pending" in statuses
    assert "assigned" in statuses
    assert all(e["order_id"] == order.id for e in events)


def test_transition_event_includes_previous_status(
    session: Session, service: DispatchService, bus: EventBus
) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    order, _ = service.create_order(session, NEAR)
    queue = bus.subscribe()
    service.advance_order(session, order, OrderStatus.PICKED_UP)
    event = queue.get_nowait()
    assert event["status"] == "picked_up"
    assert event["previous_status"] == "assigned"
