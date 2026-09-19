"""SemanticQueue: coalescing "one in-flight, latest pending" wrapper.

Enforces the v3 plan's rule for the semantic path:

    "Keep one active semantic request plus the latest pending utterance;
     bound requests and retries."

Design:
    * submit(utterance, mode_revision, now) enqueues an utterance. If
      nothing is in-flight, the utterance goes into the in-flight slot.
      Otherwise it replaces whatever is currently in the pending slot;
      any previous pending utterance is dropped and appended to
      `dropped` for logging.
    * drain(now) runs the parse function on the in-flight slot, promotes
      pending to in-flight, and returns the resulting Cue. Timeout is
      detected here (queue-level) so the parse function does not have to
      implement it. Any exception in parse also yields a safe HOLD Cue.
    * The mode_revision captured at submit time is written onto the
      returned Cue so DirectorSession can reject stale-revision cues.

Parse function is injected so tests can hand in a fake. The real caller
would pass cue_api.semantics.parser.parse or a wrapper.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from cue_api.semantics.parser import (
    Action,
    Cue,
    Intent,
    Scope,
    TemporalIntent,
)

ParseFn = Callable[[str], tuple[Cue, float]]


@dataclass
class QueueEntry:
    utterance: str
    mode_revision: int
    submitted_at: float
    utterance_id: str = ""
    created_at: float = 0.0


@dataclass
class DroppedEntry:
    utterance: str
    mode_revision: int
    submitted_at: float
    reason: str
    dropped_at: float


@dataclass
class SemanticQueue:
    parse_fn: ParseFn
    timeout_s: float = 5.0
    _in_flight: QueueEntry | None = None
    _pending: QueueEntry | None = None
    dropped: list[DroppedEntry] = field(default_factory=list)

    # ---- submit / drain ------------------------------------------------

    def submit(
        self,
        utterance: str,
        mode_revision: int,
        now: float,
        *,
        utterance_id: str = "",
        created_at: float = 0.0,
    ) -> None:
        """Enqueue an utterance. Drops previous pending if any.

        Optional utterance_id and created_at are threaded to the returned
        Cue so downstream consumers (DirectorSession) can apply
        correction and staleness rules unchanged.
        """
        entry = QueueEntry(
            utterance=utterance,
            mode_revision=mode_revision,
            submitted_at=now,
            utterance_id=utterance_id,
            created_at=created_at,
        )
        if self._in_flight is None:
            self._in_flight = entry
            return
        if self._pending is not None:
            self.dropped.append(DroppedEntry(
                utterance=self._pending.utterance,
                mode_revision=self._pending.mode_revision,
                submitted_at=self._pending.submitted_at,
                reason="superseded_by_newer_pending",
                dropped_at=now,
            ))
        self._pending = entry

    def drain(self, now: float) -> Cue | None:
        """Parse the in-flight slot and return the Cue.

        Returns None when the queue is empty. Advances pending -> in-flight
        after each drain, so callers can loop until None.
        """
        if self._in_flight is None:
            return None
        entry = self._in_flight
        age = now - entry.submitted_at
        if age > self.timeout_s:
            cue = self._safe_hold(entry, reason=f"timeout {age:.2f}s")
        else:
            try:
                cue, _ms = self.parse_fn(entry.utterance)
            except TimeoutError:
                cue = self._safe_hold(entry, reason="parse timeout")
            except Exception as e:  # noqa: BLE001 -- defensive: any parse error -> safe HOLD
                cue = self._safe_hold(entry, reason=f"parse error: {type(e).__name__}")
            else:
                cue.mode_revision = entry.mode_revision
                if not cue.evidence_text:
                    cue.evidence_text = entry.utterance
                if entry.utterance_id and not cue.utterance_id:
                    cue.utterance_id = entry.utterance_id
                if entry.created_at and not cue.created_at:
                    cue.created_at = entry.created_at
        # Advance the queue.
        self._in_flight = self._pending
        self._pending = None
        return cue

    # ---- state -----------------------------------------------------

    @property
    def in_flight(self) -> QueueEntry | None:
        return self._in_flight

    @property
    def pending(self) -> QueueEntry | None:
        return self._pending

    def clear(self) -> None:
        """Discard both slots. Preserves the dropped log."""
        self._in_flight = None
        self._pending = None

    # ---- internals -----------------------------------------------------

    def _safe_hold(self, entry: QueueEntry, *, reason: str) -> Cue:
        return Cue(
            target_guest_ids=[],
            scope=Scope.NONE,
            intent=Intent.NONE,
            temporal_intent=TemporalIntent.UNCERTAIN,
            action=Action.HOLD,
            evidence_text=entry.utterance,
            utterance_id=entry.utterance_id,
            created_at=entry.created_at,
            mode_revision=entry.mode_revision,
        )

    def to_summary(self) -> dict:
        """For DecisionRecord / debugging."""
        def _entry(e: QueueEntry | None) -> dict | None:
            return None if e is None else {
                "utterance": e.utterance,
                "mode_revision": e.mode_revision,
                "submitted_at": e.submitted_at,
            }
        return {
            "in_flight": _entry(self._in_flight),
            "pending": _entry(self._pending),
            "dropped_count": len(self.dropped),
        }


# Marker constants for callers who want to detect the queue's safe-HOLD cue.
SAFE_HOLD_REASON_PREFIX = "SAFE_HOLD"
