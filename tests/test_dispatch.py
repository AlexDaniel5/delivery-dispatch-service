"""Tests for core dispatch behaviour: assignment, radius and ETA."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.dispatch import DispatchService
from app.schemas import OrderCreate
from app.state_machine import CourierStatus, OrderStatus
from tests.conftest import ServiceFactory, add_courier

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.05, dropoff_lon=0.05)


def test_assign_to_available_courier(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    order, created = service.create_order(session, NEAR)
    assert created is True
    assert order.status == OrderStatus.ASSIGNED
    assert order.courier_id == "c1"


def test_assignment_sets_distance_and_eta(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    order, _ = service.create_order(session, NEAR)
    assert order.distance_km is not None
    assert order.eta_minutes is not None
    assert order.distance_km >= 0.0
    assert order.eta_minutes >= 0.0


def test_courier_marked_busy_after_assignment(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0)
    order, _ = service.create_order(session, NEAR)
    session.refresh(courier)
    assert courier.status == CourierStatus.BUSY
    assert courier.current_order_id == order.id


def test_nearest_courier_is_chosen(session: Session, service: DispatchService) -> None:
    add_courier(session, courier_id="far", lat=0.08, lon=0.08)
    add_courier(session, courier_id="near", lat=0.001, lon=0.001)
    order, _ = service.create_order(session, NEAR)
    assert order.courier_id == "near"


def test_courier_outside_radius_not_assigned(
    session: Session, make_service: ServiceFactory
) -> None:
    svc = make_service(radius_km=1.0)
    # ~15.7 km away, outside the 1 km radius.
    add_courier(session, lat=0.1, lon=0.1)
    order, _ = svc.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED
    assert order.courier_id is None


def test_courier_just_inside_radius_is_assigned(
    session: Session, make_service: ServiceFactory
) -> None:
    svc = make_service(radius_km=20.0)
    add_courier(session, lat=0.1, lon=0.1)  # ~15.7 km
    order, _ = svc.create_order(session, NEAR)
    assert order.status == OrderStatus.ASSIGNED


def test_eta_uses_configured_speed(session: Session, make_service: ServiceFactory) -> None:
    slow = make_service(speed_kmh=10.0)
    add_courier(session, lat=0.05, lon=0.05)  # ~7.8 km, inside the 10 km radius
    order, _ = slow.create_order(session, NEAR)
    assert order.distance_km is not None and order.eta_minutes is not None
    expected = (order.distance_km / 10.0) * 60.0
    assert abs(order.eta_minutes - expected) < 1e-6


def test_offline_courier_not_assigned(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0, status=CourierStatus.OFFLINE)
    order, _ = service.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED


def test_busy_courier_not_assigned(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0, status=CourierStatus.BUSY)
    order, _ = service.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED


def test_pickup_location_drives_distance_not_dropoff(
    session: Session, make_service: ServiceFactory
) -> None:
    svc = make_service(radius_km=5.0)
    # Courier is near pickup (0,0) but far from dropoff — should still assign.
    add_courier(session, lat=0.0, lon=0.0)
    order = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=1.0, dropoff_lon=1.0)
    created, _ = svc.create_order(session, order)
    assert created.status == OrderStatus.ASSIGNED
