"""For C's live lane: post decisions and captions to the desk feed without blocking the lane."""

from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from typing import Any


def caption_from_deepgram(message: dict[str, Any]) -> dict[str, Any] | None:
    """A Deepgram v1 Results frame to a feed caption item; None when there is no text."""
    if message.get("type") != "Results":
        return None
    channel = message.get("channel") or {}
    alternatives = channel.get("alternatives") or []
    alt = alternatives[0] if alternatives and isinstance(alternatives[0], dict) else {}
    text = str(alt.get("transcript") or "").strip()
    if not text:
        return None
    item: dict[str, Any] = {
        "kind": "caption",
        "text": text,
        "final": bool(message.get("is_final")),
        "speechFinal": bool(message.get("speech_final")),
    }
    if alt.get("confidence") is not None:
        item["confidence"] = alt["confidence"]
    words = alt.get("words")
    if isinstance(words, list) and words:
        item["words"] = [
            {k: w.get(k) for k in ("word", "punctuated_word", "confidence") if k in w}
            for w in words
            if isinstance(w, dict)
        ][:200]
    return item


class DeskFeed:
    """Background poster.

    Items queue up; a full queue drops the oldest; errors are counted, not raised.
    """

    def __init__(
        self,
        api_base: str,
        event_id: str,
        producer_secret: str,
        *,
        maxsize: int = 500,
        timeout_s: float = 3.0,
    ) -> None:
        self.url = f"{api_base.rstrip('/')}/api/v1/events/{event_id}/desk/feed"
        self._secret = producer_secret
        self._timeout = timeout_s
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self.errors = 0
        self.posted = 0
        self._thread = threading.Thread(target=self._run, name="desk-feed", daemon=True)
        self._thread.start()

    def post(self, item: dict[str, Any]) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
        self._queue.put_nowait(item)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            batch = [item]
            while len(batch) < 50:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            body = json.dumps(batch).encode()
            request = urllib.request.Request(
                self.url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json", "X-CUE-Producer-Secret": self._secret},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout):
                    self.posted += len(batch)
            except (urllib.error.URLError, OSError, TimeoutError):
                self.errors += 1


class DeskFeedSender:
    """C's DecisionSender that also posts each DecisionEvent to the desk feed."""

    def __init__(self, feed: DeskFeed, inner: Any | None = None) -> None:
        self._feed = feed
        self._inner = inner

    def send(self, event: Any, *, decision_seq: int) -> None:
        if self._inner is not None:
            self._inner.send(event, decision_seq=decision_seq)
        try:
            payload = json.loads(event.model_dump_json(by_alias=True))
        except Exception:  # noqa: BLE001 -- a non-pydantic event is posted as-is
            payload = event if isinstance(event, dict) else {"decisionSeq": decision_seq}
        self._feed.post({"kind": "decision", "event": payload, "decisionSeq": decision_seq})
