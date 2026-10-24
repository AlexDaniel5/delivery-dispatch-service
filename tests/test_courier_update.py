"""Tests for courier location and availability updates."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dispatch import CourierBusyError, DispatchService
from app.schemas import OrderCreate
from app.state_machine import CourierStatus, OrderStatus
from tests.conftest import ServiceFactory, add_courier

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.01, dropoff_lon=0.01)
COURIER = {"name": "Alice", "lat": 0.0, "lon": 0.0}
ORDER = {"pickup_lat": 0.0, "pickup_lon": 0.0, "dropoff_lat": 0.01, "dropoff_lon": 0.01}


# -- service level ---------------------------------------------------------


def test_going_offline_then_online_drains_queue(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0, status=CourierStatus.OFFLINE)
    order, _ = service.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED

    service.update_courier(session, courier, status=CourierStatus.AVAILABLE)
    session.refresh(order)
    assert order.status == OrderStatus.ASSIGNED


def test_moving_into_range_drains_queue(session: Session, make_service: ServiceFactory) -> None:
    svc = make_service(radius_km=2.0)
    courier = add_courier(session, lat=0.2, lon=0.2)  # ~31 km away, out of range
    order, _ = svc.create_order(session, NEAR)
    assert order.status == OrderStatus.QUEUED

    svc.update_courier(session, courier, lat=0.0, lon=0.0)  # now at pickup
    session.refresh(order)
    assert order.status == OrderStatus.ASSIGNED


def test_set_offline(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0)
    service.update_courier(session, courier, status=CourierStatus.OFFLINE)
    assert courier.status == CourierStatus.OFFLINE


def test_change_busy_courier_status_raises(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0)
    service.create_order(session, NEAR)  # makes the courier busy
    session.refresh(courier)
    assert courier.status == CourierStatus.BUSY
    with pytest.raises(CourierBusyError):
        service.update_courier(session, courier, status=CourierStatus.OFFLINE)


def test_move_busy_courier_location_allowed(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0)
    service.create_order(session, NEAR)
    session.refresh(courier)
    updated = service.update_courier(session, courier, lat=1.0, lon=1.0)
    assert updated.lat == 1.0
    assert updated.status == CourierStatus.BUSY


def test_invalid_status_value_rejected(session: Session, service: DispatchService) -> None:
    courier = add_courier(session, lat=0.0, lon=0.0)
    with pytest.raises(ValueError):
        service.update_courier(session, courier, status=CourierStatus.BUSY)


# -- API level -------------------------------------------------------------


def test_patch_courier_location(client: TestClient) -> None:
    courier = client.post("/couriers", json=COURIER).json()
    resp = client.patch(f"/couriers/{courier['id']}", json={"lat": 5.0, "lon": 6.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["lat"] == 5.0
    assert body["lon"] == 6.0


def test_patch_courier_offline(client: TestClient) -> None:
    courier = client.post("/couriers", json=COURIER).json()
    resp = client.patch(f"/couriers/{courier['id']}", json={"status": "offline"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "offline"


def test_patch_coming_online_assigns_queued_order(client: TestClient) -> None:
    courier = client.post("/couriers", json=COURIER).json()
    client.patch(f"/couriers/{courier['id']}", json={"status": "offline"})
    order = client.post("/orders", json=ORDER).json()
    assert order["status"] == "queued"

    client.patch(f"/couriers/{courier['id']}", json={"status": "available"})
    refreshed = client.get(f"/orders/{order['id']}").json()
    assert refreshed["status"] == "assigned"


def test_patch_busy_courier_status_409(client: TestClient) -> None:
    courier = client.post("/couriers", json=COURIER).json()
    client.post("/orders", json=ORDER)  # courier becomes busy
    resp = client.patch(f"/couriers/{courier['id']}", json={"status": "offline"})
    assert resp.status_code == 409


def test_patch_status_busy_is_422(client: TestClient) -> None:
    courier = client.post("/couriers", json=COURIER).json()
    resp = client.patch(f"/couriers/{courier['id']}", json={"status": "busy"})
    assert resp.status_code == 422


def test_patch_unknown_courier_404(client: TestClient) -> None:
    resp = client.patch("/couriers/nope", json={"lat": 1.0})
    assert resp.status_code == 404
