"""What C's live lane posts for the desk: captions, decisions, Deepgram config.

Bounded per event. Subscribers are asyncio queues on the API's loop; a slow desk
drops its oldest items rather than stalling the poster.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

FEED_KINDS = ("caption", "decision", "deepgram_config", "caption_status", "latency", "rating")
MAX_ITEMS = 200
QUEUE_SIZE = 500


@dataclass
class EventFeed:
    captions: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_ITEMS))
    decisions: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_ITEMS))
    ratings: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_ITEMS))
    deepgram_config: dict[str, Any] | None = None
    caption_status: dict[str, Any] | None = None
    latency: dict[str, Any] | None = None
    last_caption_at: float | None = None


class DeskFeedStore:
    def __init__(self) -> None:
        self._events: dict[str, EventFeed] = {}
        self._subscribers: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._lock = threading.Lock()

    def feed(self, event_id: str) -> EventFeed:
        with self._lock:
            return self._events.setdefault(event_id, EventFeed())

    def publish(self, event_id: str, item: dict[str, Any], now: float | None = None) -> bool:
        """Store one feed item and hand it to every subscriber. False if the kind is unknown."""
        kind = item.get("kind")
        if kind not in FEED_KINDS:
            return False
        now = time.time() if now is None else now
        stamped = {**item, "at": item.get("at") or now}
        with self._lock:
            feed = self._events.setdefault(event_id, EventFeed())
            if kind == "caption":
                feed.captions.append(stamped)
                feed.last_caption_at = now
            elif kind == "decision":
                feed.decisions.append(stamped)
            elif kind == "rating":
                feed.ratings.append(stamped)
            elif kind == "deepgram_config":
                feed.deepgram_config = stamped
            elif kind == "caption_status":
                feed.caption_status = stamped
            elif kind == "latency":
                feed.latency = stamped
            targets = list(self._subscribers.get(event_id, ()))
        for loop, queue in targets:
            loop.call_soon_threadsafe(_offer, queue, stamped)
        return True

    def subscribe(self, event_id: str) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.setdefault(event_id, set()).add((loop, queue))
        return loop, queue

    def unsubscribe(
        self, event_id: str, handle: tuple[asyncio.AbstractEventLoop, asyncio.Queue]
    ) -> None:
        with self._lock:
            subscribers = self._subscribers.get(event_id)
            if subscribers:
                subscribers.discard(handle)

    def caption_connected(
        self, event_id: str, now: float | None = None, within_s: float = 10.0
    ) -> bool:
        feed = self.feed(event_id)
        now = time.time() if now is None else now
        if feed.caption_status is not None and "connected" in feed.caption_status:
            if not feed.caption_status["connected"]:
                return False
        return feed.last_caption_at is not None and now - feed.last_caption_at <= within_s


def _offer(queue: asyncio.Queue, item: dict[str, Any]) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(item)
