"""Explicit order lifecycle state machine."""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    """Lifecycle states of an order."""

    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class CourierStatus(StrEnum):
    """Availability states of a courier."""

    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


# Allowed order transitions. A state mapping to an empty set is terminal.
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset(
        {OrderStatus.ASSIGNED, OrderStatus.QUEUED, OrderStatus.CANCELLED}
    ),
    OrderStatus.QUEUED: frozenset({OrderStatus.ASSIGNED, OrderStatus.CANCELLED}),
    OrderStatus.ASSIGNED: frozenset({OrderStatus.PICKED_UP, OrderStatus.CANCELLED}),
    OrderStatus.PICKED_UP: frozenset({OrderStatus.DELIVERED, OrderStatus.CANCELLED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}

TERMINAL_STATES: frozenset[OrderStatus] = frozenset(
    state for state, nxt in ALLOWED_TRANSITIONS.items() if not nxt
)


class InvalidTransitionError(ValueError):
    """Raised when an order is asked to make a transition that is not allowed."""

    def __init__(self, current: OrderStatus, target: OrderStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid transition {current.value} -> {target.value}")


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    """Return ``True`` if ``current`` -> ``target`` is a permitted transition."""
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: OrderStatus, target: OrderStatus) -> None:
    """Raise :class:`InvalidTransitionError` unless the transition is permitted."""
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)


def is_terminal(status: OrderStatus) -> bool:
    """Return ``True`` if ``status`` is a terminal state."""
    return status in TERMINAL_STATES
