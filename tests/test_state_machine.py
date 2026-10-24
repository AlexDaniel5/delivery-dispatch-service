"""Tests for the order lifecycle state machine."""

from __future__ import annotations

import pytest

from app.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    OrderStatus,
    assert_transition,
    can_transition,
    is_terminal,
)

VALID = [
    (OrderStatus.PENDING, OrderStatus.ASSIGNED),
    (OrderStatus.PENDING, OrderStatus.QUEUED),
    (OrderStatus.PENDING, OrderStatus.CANCELLED),
    (OrderStatus.QUEUED, OrderStatus.ASSIGNED),
    (OrderStatus.QUEUED, OrderStatus.CANCELLED),
    (OrderStatus.ASSIGNED, OrderStatus.PICKED_UP),
    (OrderStatus.ASSIGNED, OrderStatus.CANCELLED),
    (OrderStatus.PICKED_UP, OrderStatus.DELIVERED),
    (OrderStatus.PICKED_UP, OrderStatus.CANCELLED),
]

INVALID = [
    (OrderStatus.PENDING, OrderStatus.PICKED_UP),
    (OrderStatus.PENDING, OrderStatus.DELIVERED),
    (OrderStatus.QUEUED, OrderStatus.PICKED_UP),
    (OrderStatus.QUEUED, OrderStatus.DELIVERED),
    (OrderStatus.QUEUED, OrderStatus.PENDING),
    (OrderStatus.ASSIGNED, OrderStatus.DELIVERED),
    (OrderStatus.ASSIGNED, OrderStatus.QUEUED),
    (OrderStatus.ASSIGNED, OrderStatus.PENDING),
    (OrderStatus.PICKED_UP, OrderStatus.ASSIGNED),
    (OrderStatus.PICKED_UP, OrderStatus.QUEUED),
    (OrderStatus.DELIVERED, OrderStatus.ASSIGNED),
    (OrderStatus.DELIVERED, OrderStatus.CANCELLED),
    (OrderStatus.DELIVERED, OrderStatus.PICKED_UP),
    (OrderStatus.CANCELLED, OrderStatus.ASSIGNED),
    (OrderStatus.CANCELLED, OrderStatus.PENDING),
    (OrderStatus.CANCELLED, OrderStatus.DELIVERED),
]


@pytest.mark.parametrize(("current", "target"), VALID)
def test_valid_transitions_allowed(current: OrderStatus, target: OrderStatus) -> None:
    assert can_transition(current, target) is True
    assert_transition(current, target)  # should not raise


@pytest.mark.parametrize(("current", "target"), INVALID)
def test_invalid_transitions_rejected(current: OrderStatus, target: OrderStatus) -> None:
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError):
        assert_transition(current, target)


def test_invalid_transition_error_attributes() -> None:
    with pytest.raises(InvalidTransitionError) as exc_info:
        assert_transition(OrderStatus.DELIVERED, OrderStatus.ASSIGNED)
    err = exc_info.value
    assert err.current == OrderStatus.DELIVERED
    assert err.target == OrderStatus.ASSIGNED
    assert "delivered" in str(err)
    assert "assigned" in str(err)


def test_no_self_transitions_allowed() -> None:
    for status in OrderStatus:
        assert can_transition(status, status) is False


def test_terminal_states() -> None:
    assert is_terminal(OrderStatus.DELIVERED) is True
    assert is_terminal(OrderStatus.CANCELLED) is True
    assert is_terminal(OrderStatus.PENDING) is False
    assert is_terminal(OrderStatus.QUEUED) is False
    assert is_terminal(OrderStatus.ASSIGNED) is False
    assert is_terminal(OrderStatus.PICKED_UP) is False


def test_terminal_states_have_no_outgoing() -> None:
    assert ALLOWED_TRANSITIONS[OrderStatus.DELIVERED] == frozenset()
    assert ALLOWED_TRANSITIONS[OrderStatus.CANCELLED] == frozenset()


def test_every_status_has_a_transition_entry() -> None:
    for status in OrderStatus:
        assert status in ALLOWED_TRANSITIONS


def test_cancellable_from_all_non_terminal_states() -> None:
    for status in (
        OrderStatus.PENDING,
        OrderStatus.QUEUED,
        OrderStatus.ASSIGNED,
        OrderStatus.PICKED_UP,
    ):
        assert can_transition(status, OrderStatus.CANCELLED)


def test_enum_values_are_strings() -> None:
    assert OrderStatus.PENDING == "pending"
    assert OrderStatus.DELIVERED.value == "delivered"
