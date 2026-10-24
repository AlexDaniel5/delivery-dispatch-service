"""Shared pytest fixtures.

The test database URL is set *before* any application module is imported so the
process-wide engine binds to a throwaway SQLite file.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

_db_fd, _db_path = tempfile.mkstemp(suffix=".db", prefix="dispatch-test-")
os.close(_db_fd)
os.environ["DISPATCH_DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import SessionLocal, get_engine  # noqa: E402
from app.dispatch import DispatchService  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Courier, Order  # noqa: E402
from app.state_machine import CourierStatus, OrderStatus  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    """Reset all tables before each test."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def session() -> Iterator[Session]:
    """A database session bound to the test engine."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def bus() -> EventBus:
    """A fresh, unbound event bus (delivers inline for sync tests)."""
    return EventBus()


@pytest.fixture
def service(bus: EventBus) -> DispatchService:
    """A dispatch service with a 10km radius and 30km/h speed."""
    settings = Settings(
        database_url=os.environ["DISPATCH_DATABASE_URL"],
        assignment_radius_km=10.0,
        courier_speed_kmh=30.0,
    )
    return DispatchService(settings=settings, bus=bus)


@pytest.fixture
def make_service(bus: EventBus) -> ServiceFactory:
    """Factory to build a service with custom radius/speed."""

    def _factory(radius_km: float = 10.0, speed_kmh: float = 30.0) -> DispatchService:
        settings = Settings(
            database_url=os.environ["DISPATCH_DATABASE_URL"],
            assignment_radius_km=radius_km,
            courier_speed_kmh=speed_kmh,
        )
        return DispatchService(settings=settings, bus=bus)

    return _factory


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI TestClient (runs lifespan: init_db + event loop binding)."""
    with TestClient(app) as test_client:
        yield test_client


# -- helpers ---------------------------------------------------------------


def add_courier(
    session: Session,
    *,
    courier_id: str = "c1",
    name: str = "Courier",
    lat: float = 0.0,
    lon: float = 0.0,
    status: CourierStatus = CourierStatus.AVAILABLE,
) -> Courier:
    """Insert a courier directly for test setup."""
    courier = Courier(id=courier_id, name=name, lat=lat, lon=lon, status=status)
    session.add(courier)
    session.commit()
    session.refresh(courier)
    return courier


def add_order(
    session: Session,
    *,
    order_id: str = "o1",
    status: OrderStatus = OrderStatus.PENDING,
    pickup: tuple[float, float] = (0.0, 0.0),
    dropoff: tuple[float, float] = (0.05, 0.05),
) -> Order:
    """Insert an order directly for test setup."""
    order = Order(
        id=order_id,
        status=status,
        pickup_lat=pickup[0],
        pickup_lon=pickup[1],
        dropoff_lat=dropoff[0],
        dropoff_lon=dropoff[1],
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


class ServiceFactory:
    """Typing stub for the ``make_service`` fixture callable."""

    def __call__(
        self, radius_km: float = 10.0, speed_kmh: float = 30.0
    ) -> DispatchService:  # pragma: no cover - typing only
        ...
