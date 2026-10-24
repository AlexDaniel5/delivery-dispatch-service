"""End-to-end API tests via the FastAPI TestClient."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

COURIER = {"name": "Alice", "lat": 0.0, "lon": 0.0}
ORDER = {"pickup_lat": 0.0, "pickup_lon": 0.0, "dropoff_lat": 0.01, "dropoff_lon": 0.01}


def _create_courier(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload = {**COURIER, **overrides}
    resp = client.post("/couriers", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_index(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "delivery-dispatch-service"
    assert body["docs"] == "/docs"


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_courier(client: TestClient) -> None:
    body = _create_courier(client)
    assert body["name"] == "Alice"
    assert body["status"] == "available"
    assert body["current_order_id"] is None
    assert "id" in body


def test_get_courier(client: TestClient) -> None:
    created = _create_courier(client)
    resp = client.get(f"/couriers/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_unknown_courier_404(client: TestClient) -> None:
    resp = client.get("/couriers/does-not-exist")
    assert resp.status_code == 404


def test_create_order_without_courier_is_queued(client: TestClient) -> None:
    resp = client.post("/orders", json=ORDER)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["courier_id"] is None


def test_create_order_with_courier_is_assigned(client: TestClient) -> None:
    courier = _create_courier(client)
    resp = client.post("/orders", json=ORDER)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "assigned"
    assert body["courier_id"] == courier["id"]
    assert body["eta_minutes"] is not None


def test_get_order(client: TestClient) -> None:
    created = client.post("/orders", json=ORDER).json()
    resp = client.get(f"/orders/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_unknown_order_404(client: TestClient) -> None:
    resp = client.get("/orders/nope")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_idempotency_key_returns_same_order(client: TestClient) -> None:
    headers = {"Idempotency-Key": "order-123"}
    first = client.post("/orders", json=ORDER, headers=headers)
    second = client.post("/orders", json=ORDER, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_without_idempotency_key_creates_two(client: TestClient) -> None:
    first = client.post("/orders", json=ORDER)
    second = client.post("/orders", json=ORDER)
    assert first.json()["id"] != second.json()["id"]


def test_invalid_coordinates_rejected(client: TestClient) -> None:
    bad = {**ORDER, "pickup_lat": 200.0}
    resp = client.post("/orders", json=bad)
    assert resp.status_code == 422


def test_status_update_lifecycle(client: TestClient) -> None:
    _create_courier(client)
    order = client.post("/orders", json=ORDER).json()
    oid = order["id"]
    assert order["status"] == "assigned"

    r1 = client.post(f"/orders/{oid}/status", json={"status": "picked_up"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "picked_up"

    r2 = client.post(f"/orders/{oid}/status", json={"status": "delivered"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "delivered"


def test_invalid_status_transition_409(client: TestClient) -> None:
    _create_courier(client)
    order = client.post("/orders", json=ORDER).json()
    oid = order["id"]
    # assigned -> delivered is not allowed.
    resp = client.post(f"/orders/{oid}/status", json={"status": "delivered"})
    assert resp.status_code == 409
    assert "invalid transition" in resp.json()["detail"]


def test_status_update_unknown_order_404(client: TestClient) -> None:
    resp = client.post("/orders/nope/status", json={"status": "cancelled"})
    assert resp.status_code == 404


def test_cancel_order(client: TestClient) -> None:
    order = client.post("/orders", json=ORDER).json()
    resp = client.post(f"/orders/{order['id']}/status", json={"status": "cancelled"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_request_id_header_present(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.headers.get("X-Request-ID")


def test_request_id_echoed_when_supplied(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Request-ID": "my-id"})
    assert resp.headers["X-Request-ID"] == "my-id"


def test_registering_courier_drains_queue(client: TestClient) -> None:
    # Order queued first...
    order = client.post("/orders", json=ORDER).json()
    assert order["status"] == "queued"
    # ...then a courier registers and should pick it up.
    _create_courier(client)
    refreshed = client.get(f"/orders/{order['id']}").json()
    assert refreshed["status"] == "assigned"


def test_delivery_frees_courier_for_next_order(client: TestClient) -> None:
    _create_courier(client)
    first = client.post("/orders", json=ORDER).json()
    second = client.post("/orders", json=ORDER).json()
    assert first["status"] == "assigned"
    assert second["status"] == "queued"

    client.post(f"/orders/{first['id']}/status", json={"status": "picked_up"})
    client.post(f"/orders/{first['id']}/status", json={"status": "delivered"})

    refreshed = client.get(f"/orders/{second['id']}").json()
    assert refreshed["status"] == "assigned"
