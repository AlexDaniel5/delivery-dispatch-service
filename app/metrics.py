"""Prometheus metrics."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from app.state_machine import OrderStatus

# A dedicated registry keeps metrics isolated and resettable in tests.
registry = CollectorRegistry()

dispatch_latency_seconds = Histogram(
    "dispatch_latency_seconds",
    "Time spent attempting to assign an order to a courier.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=registry,
)

orders_by_status = Gauge(
    "orders_by_status",
    "Current number of orders in each lifecycle status.",
    labelnames=("status",),
    registry=registry,
)

orders_created_total = Counter(
    "orders_created_total",
    "Total number of orders created.",
    registry=registry,
)

assignments_total = Counter(
    "assignments_total",
    "Total number of successful courier assignments.",
    registry=registry,
)


def set_status_counts(counts: dict[OrderStatus, int]) -> None:
    """Set the ``orders_by_status`` gauge from a status->count mapping.

    Every known status is written (missing ones as ``0``) so stale labels do
    not linger after orders leave a state.
    """
    for status in OrderStatus:
        orders_by_status.labels(status=status.value).set(counts.get(status, 0))
