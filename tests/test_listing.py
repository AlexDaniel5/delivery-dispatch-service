"""Tests for list/filter/pagination endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

COURIER = {"name": "Alice", "lat": 0.0, "lon": 0.0}
ORDER = {"pickup_lat": 0.0, "pickup_lon": 0.0, "dropoff_lat": 0.01, "dropoff_lon": 0.01}


def test_list_orders_empty(client: TestClient) -> None:
    resp = client.get("/orders")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_orders_returns_all(client: TestClient) -> None:
    for _ in range(3):
        client.post("/orders", json=ORDER)
    body = client.get("/orders").json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_list_orders_filter_by_status(client: TestClient) -> None:
    client.post("/couriers", json=COURIER)
    client.post("/orders", json=ORDER)  # assigned
    client.post("/orders", json=ORDER)  # queued (no courier left)

    assigned = client.get("/orders", params={"status": "assigned"}).json()
    assert assigned["total"] == 1
    assert assigned["items"][0]["status"] == "assigned"

    queued = client.get("/orders", params={"status": "queued"}).json()
    assert queued["total"] == 1


def test_list_orders_filter_by_courier(client: TestClient) -> None:
    courier = client.post("/couriers", json=COURIER).json()
    client.post("/orders", json=ORDER)  # assigned to this courier
    client.post("/orders", json=ORDER)  # queued, no courier

    body = client.get("/orders", params={"courier_id": courier["id"]}).json()
    assert body["total"] == 1
    assert body["items"][0]["courier_id"] == courier["id"]


def test_list_orders_pagination(client: TestClient) -> None:
    for _ in range(5):
        client.post("/orders", json=ORDER)
    page1 = client.get("/orders", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/orders", params={"limit": 2, "offset": 2}).json()
    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    ids1 = {o["id"] for o in page1["items"]}
    ids2 = {o["id"] for o in page2["items"]}
    assert ids1.isdisjoint(ids2)


def test_list_orders_newest_first(client: TestClient) -> None:
    first = client.post("/orders", json=ORDER).json()
    second = client.post("/orders", json=ORDER).json()
    items = client.get("/orders").json()["items"]
    # Most recent first.
    assert items[0]["id"] == second["id"]
    assert items[1]["id"] == first["id"]


def test_list_orders_limit_validation(client: TestClient) -> None:
    assert client.get("/orders", params={"limit": 0}).status_code == 422
    assert client.get("/orders", params={"limit": 999}).status_code == 422
    assert client.get("/orders", params={"offset": -1}).status_code == 422


def test_list_couriers(client: TestClient) -> None:
    client.post("/couriers", json=COURIER)
    client.post("/couriers", json={**COURIER, "name": "Bob"})
    body = client.get("/couriers").json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_couriers_filter_by_status(client: TestClient) -> None:
    c1 = client.post("/couriers", json=COURIER).json()
    client.post("/couriers", json={**COURIER, "name": "Bob"})
    client.patch(f"/couriers/{c1['id']}", json={"status": "offline"})

    available = client.get("/couriers", params={"status": "available"}).json()
    offline = client.get("/couriers", params={"status": "offline"}).json()
    assert available["total"] == 1
    assert offline["total"] == 1
    assert offline["items"][0]["id"] == c1["id"]
