"""Tests for API-key authentication on write endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

COURIER = {"name": "Alice", "lat": 0.0, "lon": 0.0}
ORDER = {"pickup_lat": 0.0, "pickup_lon": 0.0, "dropoff_lat": 0.01, "dropoff_lon": 0.01}


@pytest.fixture
def auth_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Enable API-key auth with two valid keys; yield one of them."""
    monkeypatch.setenv("DISPATCH_API_KEYS", "secret1, secret2")
    get_settings.cache_clear()
    yield "secret1"
    get_settings.cache_clear()


def test_auth_disabled_by_default(client: TestClient) -> None:
    # No keys configured -> writes allowed without a key.
    assert client.post("/couriers", json=COURIER).status_code == 201


def test_write_without_key_401(client: TestClient, auth_enabled: str) -> None:
    resp = client.post("/couriers", json=COURIER)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing API key"


def test_write_with_wrong_key_403(client: TestClient, auth_enabled: str) -> None:
    resp = client.post("/couriers", json=COURIER, headers={"X-API-Key": "nope"})
    assert resp.status_code == 403


def test_write_with_valid_key_ok(client: TestClient, auth_enabled: str) -> None:
    resp = client.post("/couriers", json=COURIER, headers={"X-API-Key": auth_enabled})
    assert resp.status_code == 201


def test_second_valid_key_ok(client: TestClient, auth_enabled: str) -> None:
    resp = client.post("/couriers", json=COURIER, headers={"X-API-Key": "secret2"})
    assert resp.status_code == 201


def test_reads_do_not_require_key(client: TestClient, auth_enabled: str) -> None:
    assert client.get("/couriers").status_code == 200
    assert client.get("/orders").status_code == 200


def test_health_and_metrics_open(client: TestClient, auth_enabled: str) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_order_create_requires_key(client: TestClient, auth_enabled: str) -> None:
    assert client.post("/orders", json=ORDER).status_code == 401
    ok = client.post("/orders", json=ORDER, headers={"X-API-Key": auth_enabled})
    assert ok.status_code == 201


def test_status_update_requires_key(client: TestClient, auth_enabled: str) -> None:
    key = {"X-API-Key": auth_enabled}
    courier = client.post("/couriers", json=COURIER, headers=key).json()  # noqa: F841
    order = client.post("/orders", json=ORDER, headers=key).json()
    # Without key -> 401.
    assert (
        client.post(f"/orders/{order['id']}/status", json={"status": "picked_up"}).status_code
        == 401
    )
    # With key -> 200.
    assert (
        client.post(
            f"/orders/{order['id']}/status", json={"status": "picked_up"}, headers=key
        ).status_code
        == 200
    )
