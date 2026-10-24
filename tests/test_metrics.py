"""Tests for Prometheus metrics."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dispatch import DispatchService
from app.metrics import registry
from app.schemas import OrderCreate
from tests.conftest import add_courier

NEAR = OrderCreate(pickup_lat=0.0, pickup_lon=0.0, dropoff_lat=0.01, dropoff_lon=0.01)


def test_orders_by_status_gauge_reflects_db(session: Session, service: DispatchService) -> None:
    # No couriers -> three queued orders.
    service.create_order(session, NEAR)
    service.create_order(session, NEAR)
    service.create_order(session, NEAR)
    queued = registry.get_sample_value("orders_by_status", {"status": "queued"})
    assert queued == 3.0


def test_assigned_gauge_updates(session: Session, service: DispatchService) -> None:
    add_courier(session, lat=0.0, lon=0.0)
    service.create_order(session, NEAR)
    assigned = registry.get_sample_value("orders_by_status", {"status": "assigned"})
    assert assigned == 1.0


def test_dispatch_latency_histogram_observes(session: Session, service: DispatchService) -> None:
    before = registry.get_sample_value("dispatch_latency_seconds_count") or 0.0
    service.create_order(session, NEAR)
    after = registry.get_sample_value("dispatch_latency_seconds_count") or 0.0
    assert after > before


def test_metrics_endpoint_returns_prometheus_text(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "dispatch_latency_seconds" in body
    assert "orders_by_status" in body


def test_orders_created_counter_increments(session: Session, service: DispatchService) -> None:
    before = registry.get_sample_value("orders_created_total") or 0.0
    service.create_order(session, NEAR)
    after = registry.get_sample_value("orders_created_total") or 0.0
    assert after == before + 1.0
