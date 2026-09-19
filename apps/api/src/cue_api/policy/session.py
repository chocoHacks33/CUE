"""DirectorSession: stateful wrapper around the pure decide() function.

Owns State across time. Adds decision sequencing, mode revisions, ACK
handling, and the AUTO-pause rules the v3 plan section "Directing logic C
owns" prescribes:

    * "Manual HOLD defeats pending/late AI decisions."  Late model output
      that was interpreted under an older mode_revision is rejected here,
      not at the parser boundary.
    * "Emergency/failure safety still works."  We keep delegating to
      decide() so an unhealthy live camera failovers to wide even during
      HOLD (decide()'s _safe_fallback handles this).
    * "Resume AUTO is explicit, including after reconnect."  on_reconnect
      and on_speech_down set an internal auto_paused flag; only
      RESUME_AUTO clears it. on_speech_up alone does not.
    * "A rejected or missing ACK never changes current_camera."  We only
      commit current_camera on on_ack(applied=True) with a matching
      decision_seq.

This module is offline and dependency-free (stdlib + cue_api). Tests
inject a fake decide() by patching or by using real cameras/state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from cue_api.policy.director import (
    Decision,
    DecisionAction,
    Mode,
    State,
    decide,
)


@dataclass
class SessionDecision:
    """decide() output enriched with sequence + mode revision.

    decision_seq   monotonically increasing across the life of the session.
    mode_revision  current at issue time; also stamped on cues so the
                   session can reject late-arriving stale-mode cues.
    """
    action: DecisionAction
    camera_id: str | None
    reason: str
    decision_seq: int
    mode_revision: int


_MANUAL = frozenset({"TAKE", "HOLD", "RESUME_AUTO", "SLATE"})


class DirectorSession:
    """Stateful wrapper around decide().

    Pure except for internal state; no I/O, no threads.
    """

    def __init__(
        self,
        *,
        current_camera: str | None = None,
        wide_camera: str | None = "CAM-WIDE",
    ) -> None:
        self._state = State(current_camera=current_camera, mode=Mode.AUTO)
        self._wide_camera = wide_camera
        self._decision_seq = 0
        self._mode_revision = 0
        self._auto_paused = False              # true after speech_down / reconnect
        self._pending_ack: dict | None = None  # {"seq", "camera", "utterance_id"}

    # ---- introspection (mainly for tests) ------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def mode_revision(self) -> int:
        return self._mode_revision

    @property
    def decision_seq(self) -> int:
        return self._decision_seq

    @property
    def auto_paused(self) -> bool:
        return self._auto_paused

    @property
    def pending_ack(self) -> dict | None:
        return dict(self._pending_ack) if self._pending_ack else None

    # ---- event handlers ------------------------------------------------

    def on_cue(
        self,
        cue: Any,
        cameras: dict,
        now: float,
        *,
        role_based: bool = False,
        role_map: dict[str, str] | None = None,
    ) -> SessionDecision:
        """Ingest one interpreted cue and return the session's decision."""
        cue_rev = getattr(cue, "mode_revision", None)
        if cue_rev is not None and cue_rev != self._mode_revision:
            return self._issue(
                DecisionAction.STAY,
                self._state.current_camera,
                (
                    f"cue from stale mode_revision {cue_rev} "
                    f"(current {self._mode_revision})"
                ),
                utterance_id=None,
            )

        if self._auto_paused:
            # Delegate to decide() with mode temporarily forced to HOLD so
            # the safety-failover path is preserved but no automatic TAKEs
            # fire until RESUME_AUTO.
            paused_state = replace(self._state, mode=Mode.HOLD)
            d = decide(cue, cameras, paused_state, now,
                       role_based=role_based, role_map=role_map)
            return self._issue_from_decide(d, cue)

        d = decide(cue, cameras, self._state, now,
                   role_based=role_based, role_map=role_map)
        return self._issue_from_decide(d, cue)

    def on_manual(self, command: str, now: float) -> SessionDecision:
        """Handle producer input. Every manual action bumps mode_revision."""
        parts = command.strip().split(None, 1)
        if not parts:
            raise ValueError("empty manual command")
        head = parts[0].upper()
        if head not in _MANUAL:
            raise ValueError(f"unknown manual command: {command!r}")

        # Bump BEFORE issuing so the issued SessionDecision carries the new
        # revision, and any in-flight AI cues on the old revision get
        # rejected at on_cue().
        self._mode_revision += 1

        if head == "HOLD":
            self._state = replace(self._state, mode=Mode.HOLD)
            return self._issue(
                DecisionAction.STAY, self._state.current_camera, "manual HOLD",
                utterance_id=None,
            )

        if head == "RESUME_AUTO":
            self._state = replace(self._state, mode=Mode.AUTO)
            self._auto_paused = False
            return self._issue(
                DecisionAction.STAY, self._state.current_camera,
                "manual RESUME_AUTO",
                utterance_id=None,
            )

        if head == "SLATE":
            return self._issue(
                DecisionAction.SLATE, None, "manual SLATE",
                utterance_id=None,
            )

        # head == "TAKE"
        if len(parts) < 2 or not parts[1].strip():
            raise ValueError("TAKE requires a camera id")
        cam = parts[1].strip()
        # Manual TAKE is authoritative producer intent: clear pause and any
        # HOLD, then propose the take. current_camera only updates on ACK.
        self._auto_paused = False
        self._state = replace(self._state, mode=Mode.AUTO)
        return self._issue(
            DecisionAction.TAKE, cam, f"manual TAKE {cam}",
            utterance_id=None,
        )

    def on_ack(self, decision_seq: int, applied: bool, now: float) -> None:
        """Compositor acknowledgement of a previously issued decision.

        applied=True commits current_camera; applied=False (or missing) is
        a no-op on current_camera per the plan.
        """
        if self._pending_ack is None:
            return
        if decision_seq != self._pending_ack["seq"]:
            # Late ACK for a superseded decision; ignore.
            return
        if applied:
            self._state = replace(
                self._state,
                current_camera=self._pending_ack["camera"],
                last_cut_time=now,
                last_utterance_id=self._pending_ack.get("utterance_id", "") or "",
            )
        # applied=False leaves state alone; either way, clear the slot.
        self._pending_ack = None

    def on_speech_down(self) -> None:
        """ASR/transport pipeline went down. Block AI TAKEs until RESUME_AUTO."""
        self._auto_paused = True

    def on_speech_up(self) -> None:
        """ASR/transport pipeline recovered.

        Deliberately does NOT clear auto_paused: the producer must issue
        RESUME_AUTO to accept AI cuts again (plan: 'Resume AUTO is
        explicit, including after reconnect.').
        """
        return

    def on_reconnect(self) -> None:
        """Backend/control transport restart.

        Bumps mode_revision so any in-flight cues from before the
        reconnect are rejected as stale, and pauses AUTO until RESUME_AUTO.
        """
        self._mode_revision += 1
        self._auto_paused = True
        # Any pending ACK is now unreachable; drop it.
        self._pending_ack = None

    # ---- internals -----------------------------------------------------

    def _issue_from_decide(
        self,
        d: Decision,
        cue: Any,
    ) -> SessionDecision:
        return self._issue(
            d.action, d.camera_id, d.reason,
            utterance_id=getattr(cue, "utterance_id", "") or None,
        )

    def _issue(
        self,
        action: DecisionAction,
        camera_id: str | None,
        reason: str,
        *,
        utterance_id: str | None,
    ) -> SessionDecision:
        self._decision_seq += 1
        seq = self._decision_seq
        sd = SessionDecision(
            action=action,
            camera_id=camera_id,
            reason=reason,
            decision_seq=seq,
            mode_revision=self._mode_revision,
        )
        # Only actions that actually change what's on the wire require an ACK.
        if action == DecisionAction.TAKE and camera_id != self._state.current_camera:
            self._pending_ack = {
                "seq": seq,
                "camera": camera_id,
                "utterance_id": utterance_id or "",
            }
        elif action == DecisionAction.SLATE and self._state.current_camera is not None:
            self._pending_ack = {"seq": seq, "camera": None, "utterance_id": ""}
        return sd
