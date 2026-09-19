"""CLane: the single entry point A's backend uses to drive the C-lane.

Composes the four pieces from Stage-0 through Stage-2 prep:

    Deepgram transcript msg -> speech.assembler.Assembler
                            -> semantics.queue.SemanticQueue
                            -> parse_fn (injected: real OpenAI parser or fake)
                            -> policy.session.DirectorSession
                            -> policy.log.DecisionLogger  (optional)
                            -> emit(DecisionRecord)       (injected callback)

No threads, no network, no globals. Everything the class needs is passed
in through __init__. Public method calls are the only way to move state.

Public API (the only eight methods A calls):
  on_transcript_message(msg, now)        -- one Deepgram Results/UtteranceEnd
  on_camera_state(cameras, now)          -- latest camera dict from A/B
  on_manual(command, now)                -- producer: TAKE X / HOLD / RESUME_AUTO / SLATE
  on_ack(decision_seq, applied, now)     -- compositor ack (D)
  on_speech_down()                       -- ASR/transport down
  on_speech_up()                         -- ASR/transport up (RESUME_AUTO still explicit)
  on_reconnect(new_epoch)                -- backend/control restart or WS reconnect
  tick(now)                              -- periodic; flushes missing-endpoint utterances
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from cue_api.policy.log import (
    CameraConsideration,
    DecisionLogger,
    DecisionRecord,
    record_from_session_decision,
)
from cue_api.policy.session import DirectorSession
from cue_api.semantics.parser import Cue
from cue_api.semantics.queue import SemanticQueue
from cue_api.speech.assembler import Assembler, FinalUtterance

ParseFn = Callable[[str], tuple[Cue, float]]
EmitFn = Callable[[DecisionRecord], None]
Clock = Callable[[], float]


class CLane:
    """Single-owner façade for A's backend."""

    def __init__(
        self,
        *,
        parse_fn: ParseFn,
        emit: EmitFn,
        logger: DecisionLogger | None = None,
        clock: Clock | None = None,
        camera_state_max_age_s: float = 1.0,
        assembler_timeout_s: float = 1.2,
        queue_timeout_s: float = 5.0,
        initial_camera: str | None = None,
        initial_audio_epoch: int = 1,
        role_based: bool = False,
        role_map: Mapping[str, str] | None = None,
    ) -> None:
        self._emit = emit
        self._logger = logger
        self._clock = clock or time.perf_counter
        self._camera_state_max_age_s = camera_state_max_age_s
        self._role_based = role_based
        self._role_map = dict(role_map or {})

        self._assembler = Assembler(
            timeout_s=assembler_timeout_s,
            audio_epoch=initial_audio_epoch,
        )
        self._queue = SemanticQueue(parse_fn=parse_fn, timeout_s=queue_timeout_s)
        self._session = DirectorSession(current_camera=initial_camera)
        self._cameras: dict[str, dict] = {}
        self._cameras_at: float | None = None

    # ---- read-only introspection (for tests / diagnostics) --------------

    @property
    def session(self) -> DirectorSession:
        return self._session

    @property
    def mode_revision(self) -> int:
        return self._session.mode_revision

    @property
    def audio_epoch(self) -> int:
        return self._assembler._audio_epoch  # noqa: SLF001 -- deliberate

    # ---- 1. Deepgram messages ------------------------------------------

    def on_transcript_message(self, msg: dict, now: float) -> None:
        events = self._assembler.feed(msg, now)
        self._process_events(events, now)

    # ---- 2. Camera state -----------------------------------------------

    def on_camera_state(self, cameras: Mapping[str, Mapping[str, Any]], now: float) -> None:
        # Shallow copy; per-camera dicts kept as-is (immutable in practice).
        self._cameras = {cid: dict(c) for cid, c in cameras.items()}
        self._cameras_at = now

    # ---- 3. Producer manual commands -----------------------------------

    def on_manual(self, command: str, now: float) -> None:
        sd = self._session.on_manual(command, now)
        self._emit_decision(sd, cue=None, now=now, considered=[])

    # ---- 4. Compositor ACKs --------------------------------------------

    def on_ack(self, decision_seq: int, applied: bool, now: float) -> None:
        self._session.on_ack(decision_seq, applied, now)

    # ---- 5-7. Lifecycle ------------------------------------------------

    def on_speech_down(self) -> None:
        self._session.on_speech_down()

    def on_speech_up(self) -> None:
        self._session.on_speech_up()

    def on_reconnect(self, new_epoch: int) -> None:
        self._assembler.reset(new_epoch)
        self._session.on_reconnect()
        # Any in-flight or pending utterance was under the old epoch/rev;
        # drop both slots so we don't drain them into stale decisions.
        self._queue.clear()

    # ---- 8. Timer tick -------------------------------------------------

    def tick(self, now: float) -> None:
        events = self._assembler.tick(now)
        self._process_events(events, now)
        # Also drive any still-pending queue work (e.g. a Cue that came
        # in before an ACK).
        self._drain_pending(now)

    # ---- internals -----------------------------------------------------

    def _process_events(self, events: list, now: float) -> None:
        for e in events:
            if isinstance(e, FinalUtterance):
                self._queue.submit(
                    e.text,
                    self._session.mode_revision,
                    now,
                    utterance_id=e.utterance_id,
                    created_at=e.ended_at if e.ended_at is not None else now,
                )
        self._drain_pending(now)

    def _drain_pending(self, now: float) -> None:
        while True:
            cue = self._queue.drain(now)
            if cue is None:
                return
            self._drive_decision(cue, now)

    def _drive_decision(self, cue: Cue, now: float) -> None:
        # Camera-state freshness gate: block named TAKEs when we haven't
        # heard from A/B recently. The plan calls this out: named cuts
        # require current camera epoch and fresh evidence. Without a
        # recent snapshot, we cannot verify either.
        if self._cameras_at is None:
            sd = self._session.note_stay(reason="camera state missing")
            self._emit_decision(sd, cue=cue, now=now, considered=[])
            return
        age = now - self._cameras_at
        if age > self._camera_state_max_age_s:
            sd = self._session.note_stay(
                reason=(
                    f"camera state expired ({age:.2f}s > "
                    f"{self._camera_state_max_age_s:.2f}s)"
                ),
            )
            self._emit_decision(sd, cue=cue, now=now,
                                considered=_snapshot(self._cameras, picked=None))
            return

        sd = self._session.on_cue(
            cue, self._cameras, now,
            role_based=self._role_based, role_map=self._role_map,
        )
        self._emit_decision(sd, cue=cue, now=now,
                            considered=_snapshot(self._cameras, picked=sd.camera_id))

    def _emit_decision(
        self,
        sd: Any,
        *,
        cue: Cue | None,
        now: float,
        considered: list[CameraConsideration],
    ) -> None:
        record = record_from_session_decision(
            sd, at=now, cue=cue,
            cameras_considered=considered,
            source="LIVE",
        )
        if self._logger is not None:
            self._logger.append(record)
        self._emit(record)


def _snapshot(
    cameras: Mapping[str, Mapping[str, Any]],
    *,
    picked: str | None,
) -> list[CameraConsideration]:
    """Build the cameras_considered rows for the log."""
    rows: list[CameraConsideration] = []
    for cid, c in cameras.items():
        rows.append(CameraConsideration(
            camera_id=cid,
            role=str(c.get("role", "")),
            healthy=bool(c.get("healthy")),
            guest_ready=c.get("guest_ready"),
            evidence_age_s=c.get("evidence_age_s"),
            picked=(cid == picked),
        ))
    return rows
