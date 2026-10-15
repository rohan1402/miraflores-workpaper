"""Live updates over server-sent events (D4).

Actions are ordinary POSTs. After the store appends an event, the API publishes it here,
and every open stream sends it on. A browser that reconnects sends Last-Event-ID and gets
everything it missed from the log first, so nothing is lost while the laptop was closed.

Websockets were rejected: nobody types into a shared field, so the server only ever
needs to talk one way.
"""

from __future__ import annotations

import asyncio
import json
import threading


class Broadcaster:
    """Fan-out from the (threaded) POST handlers to the (async) streams."""

    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, item: dict) -> None:
        """Safe to call from any thread: hands the item to the event loop for each subscriber."""
        if self._loop is None:
            return
        with self._lock:
            queues = list(self._subscribers)
        for queue in queues:
            self._loop.call_soon_threadsafe(queue.put_nowait, item)


async def event_stream(backlog, queue: asyncio.Queue, last_id: int, visible, render, is_disconnected,
                       heartbeat: float = 15.0):
    """Yield the events after `last_id` from the log, then live ones as they are published.

    backlog(last_id) -> list of event dicts; visible(event) -> bool for this person;
    render(event) -> the masked data to send. Subscribe before calling, so nothing published
    between reading the backlog and waiting is missed; ids already sent are skipped.
    """
    seen = last_id
    for item in await backlog(last_id):
        seen = item["id"]
        if visible(item):
            yield sse(item["id"], "wp-event", render(item))
    while not await is_disconnected():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
        except asyncio.TimeoutError:
            yield HEARTBEAT
            continue
        if item["id"] <= seen:
            continue
        seen = item["id"]
        if visible(item):
            yield sse(item["id"], "wp-event", render(item))


def sse(event_id: int, kind: str, data: dict) -> str:
    """One server-sent event, in the wire format the browser's EventSource reads."""
    return f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


HEARTBEAT = ": keep-alive\n\n"  # a comment line; keeps proxies from closing an idle stream
