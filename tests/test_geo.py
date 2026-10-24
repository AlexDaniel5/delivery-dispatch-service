"""Tests for haversine distance and ETA."""

from __future__ import annotations

import math

import pytest

from app.geo import eta_minutes, haversine_km


def test_zero_distance() -> None:
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)


def test_symmetry() -> None:
    a = haversine_km(51.5, -0.12, 48.85, 2.35)
    b = haversine_km(48.85, 2.35, 51.5, -0.12)
    assert a == pytest.approx(b)


def test_known_distance_london_paris() -> None:
    # London to Paris is ~343 km.
    distance = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert distance == pytest.approx(343.0, abs=5.0)


def test_one_degree_latitude_is_about_111km() -> None:
    distance = haversine_km(0.0, 0.0, 1.0, 0.0)
    assert distance == pytest.approx(111.19, abs=0.5)


def test_small_offset_is_small_distance() -> None:
    distance = haversine_km(0.0, 0.0, 0.01, 0.01)
    assert 1.0 < distance < 2.0


def test_antipodal_is_half_circumference() -> None:
    distance = haversine_km(0.0, 0.0, 0.0, 180.0)
    half_circumference = math.pi * 6371.0088
    assert distance == pytest.approx(half_circumference, rel=0.001)


def test_eta_basic() -> None:
    # 30 km at 30 km/h -> 60 minutes.
    assert eta_minutes(30.0, 30.0) == pytest.approx(60.0)


def test_eta_zero_distance() -> None:
    assert eta_minutes(0.0, 25.0) == pytest.approx(0.0)


def test_eta_scales_with_distance() -> None:
    assert eta_minutes(10.0, 30.0) == pytest.approx(20.0)


@pytest.mark.parametrize("speed", [0.0, -1.0, -30.0])
def test_eta_rejects_nonpositive_speed(speed: float) -> None:
    with pytest.raises(ValueError):
        eta_minutes(5.0, speed)
