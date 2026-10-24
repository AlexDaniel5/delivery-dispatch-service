"""In-process pub/sub event bus for order status changes.

The bus is safe to publish to from both the asyncio event loop and from worker
threads (FastAPI runs synchronous route handlers in a threadpool). Subscribers
receive events through an :class:`asyncio.Queue` consumed by WebSocket handlers.
"""

from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    """A minimal fan-out event bus bridging sync producers and async consumers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Record the running event loop so sync producers can publish safely."""
        self._loop = loop or asyncio.get_event_loop()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register and return a new subscriber queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue."""
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        """Publish ``event`` to all subscribers from any thread."""
        loop = self._loop
        for queue in list(self._subscribers):
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(queue.put_nowait, event)
            else:
                # No running loop (e.g. pure unit test): deliver inline.
                queue.put_nowait(event)


# Process-wide default bus.
event_bus = EventBus()
