"""Tests for WebSocket order-status streaming."""

from __future__ import annotations

from fastapi.testclient import TestClient

ORDER = {"pickup_lat": 0.0, "pickup_lon": 0.0, "dropoff_lat": 0.01, "dropoff_lon": 0.01}
COURIER = {"name": "Alice", "lat": 0.0, "lon": 0.0}


def test_websocket_receives_order_created_event(client: TestClient) -> None:
    with client.websocket_connect("/ws/orders") as ws:
        order = client.post("/orders", json=ORDER).json()
        event = ws.receive_json()
        assert event["type"] == "order_status"
        assert event["order_id"] == order["id"]
        assert event["status"] == "pending"


def test_websocket_streams_transition_events(client: TestClient) -> None:
    client.post("/couriers", json=COURIER)
    with client.websocket_connect("/ws/orders") as ws:
        order = client.post("/orders", json=ORDER).json()
        # Expect pending then assigned.
        statuses = {ws.receive_json()["status"], ws.receive_json()["status"]}
        assert statuses == {"pending", "assigned"}

        client.post(f"/orders/{order['id']}/status", json={"status": "picked_up"})
        event = ws.receive_json()
        assert event["status"] == "picked_up"
        assert event["previous_status"] == "assigned"


def test_websocket_multiple_clients_receive_broadcast(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws/orders") as ws1,
        client.websocket_connect("/ws/orders") as ws2,
    ):
        client.post("/orders", json=ORDER)
        assert ws1.receive_json()["status"] == "pending"
        assert ws2.receive_json()["status"] == "pending"
