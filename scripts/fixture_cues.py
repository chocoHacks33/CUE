"""Fixture replay for the C-lane: scripted cue timeline through DirectorSession.

Offline only. No mic, no Deepgram, no LLM. Every emitted line is stamped
`"source": "FIXTURE"` so a downstream reader can never confuse a replay
with a live decision.

Timeline exercised:
  1. Future mention  -> STAY (temporal_intent != NOW)
  2. Immediate intro -> TAKE the guest camera (role_based mapping)
  3. Guest camera covered mid-utterance -> WIDE fallback
  4. Manual HOLD from producer -> STAY, mode_revision bumps
  5. Late cue interpreted before the HOLD (older mode_revision) -> rejected
  6. Correction across the same utterance -> single final target (Daniel)

Usage:
  python scripts/fixture_cues.py                    # print JSONL to stdout
  python scripts/fixture_cues.py --out demo.jsonl   # append to a file
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cue_api.policy.log import (  # noqa: E402
    CameraConsideration,
    DecisionLogger,
    record_from_session_decision,
)
from cue_api.policy.session import DirectorSession  # noqa: E402
from cue_api.semantics.parser import (  # noqa: E402
    Action,
    Cue,
    Intent,
    Scope,
    TemporalIntent,
)

ROLE_MAP = {"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"}


def _cams(*, guest_healthy: bool = True) -> dict:
    return {
        "CAM-HOST": {
            "role": "host", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
            "guest_ready": True,
        },
        "CAM-GUEST": {
            "role": "guest", "healthy": guest_healthy, "epoch": 1,
            "confirmed_guest_ids": ["sarah"], "evidence_age_s": 0.4,
            "guest_ready": True,
        },
        "CAM-WIDE": {
            "role": "wide", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
            "guest_ready": True,
        },
    }


def _cue(text, *, temporal, targets, scope, mode_rev, utt_id, at):
    return Cue(
        target_guest_ids=list(targets),
        scope=scope,
        intent=Intent.INTRODUCE if temporal == TemporalIntent.NOW else Intent.MENTION,
        temporal_intent=temporal,
        action=Action.SHOW if (temporal == TemporalIntent.NOW and len(targets) == 1) else Action.HOLD,
        evidence_text=text,
        utterance_id=utt_id,
        created_at=at,
        mode_revision=mode_rev,
    )


def _considered(cams: dict, picked_id: str | None) -> list[CameraConsideration]:
    out: list[CameraConsideration] = []
    for cid, c in cams.items():
        out.append(CameraConsideration(
            camera_id=cid,
            role=c.get("role", ""),
            healthy=bool(c.get("healthy")),
            guest_ready=c.get("guest_ready"),
            evidence_age_s=c.get("evidence_age_s"),
            picked=(cid == picked_id),
        ))
    return out


def _emit(logger: DecisionLogger | None, record) -> None:
    line = record.to_json()
    print(line)
    if logger is not None:
        logger.append(record)


def run(logger: DecisionLogger | None = None) -> int:
    session = DirectorSession(current_camera="CAM-HOST")
    t = 1_000.0

    # Step 1: future mention (spoken -> parsed -> submitted to session)
    t += 0.2
    cue = _cue(
        "Sarah joins us after the break.",
        temporal=TemporalIntent.FUTURE, targets=["sarah"],
        scope=Scope.SINGLE, mode_rev=session.mode_revision,
        utt_id="utt-1", at=t,
    )
    d = session.on_cue(cue, _cams(), t, role_based=True, role_map=ROLE_MAP)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=cue,
        cameras_considered=_considered(_cams(), d.camera_id),
        latencies_ms={"asr": 320, "cue": 850, "decide": 1, "total": 1171},
        source="FIXTURE",
    ))

    # Step 2: immediate intro
    t += 3.0
    cue = _cue(
        "Please welcome Sarah Tan.",
        temporal=TemporalIntent.NOW, targets=["sarah"],
        scope=Scope.SINGLE, mode_rev=session.mode_revision,
        utt_id="utt-2", at=t,
    )
    d = session.on_cue(cue, _cams(), t, role_based=True, role_map=ROLE_MAP)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=cue,
        cameras_considered=_considered(_cams(), d.camera_id),
        latencies_ms={"asr": 305, "cue": 820, "decide": 1, "total": 1126},
        source="FIXTURE",
    ))
    session.on_ack(d.decision_seq, applied=True, now=t + 0.05)

    # Step 3: guest camera covered mid-utterance -> WIDE fallback
    t += 2.6
    cue = _cue(
        "Sarah, could you answer that?",
        temporal=TemporalIntent.NOW, targets=["sarah"],
        scope=Scope.SINGLE, mode_rev=session.mode_revision,
        utt_id="utt-3", at=t,
    )
    covered = _cams(guest_healthy=False)
    d = session.on_cue(cue, covered, t, role_based=True, role_map=ROLE_MAP)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=cue,
        cameras_considered=_considered(covered, d.camera_id),
        latencies_ms={"asr": 310, "cue": 780, "decide": 1, "total": 1091},
        source="FIXTURE",
    ))
    session.on_ack(d.decision_seq, applied=True, now=t + 0.05)

    # Step 4: manual HOLD
    t += 1.4
    d = session.on_manual("HOLD", t)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=None,
        cameras_considered=[], latencies_ms={"decide": 0, "total": 0},
        source="FIXTURE",
    ))

    # Step 5: late cue interpreted BEFORE the HOLD (older mode_revision)
    t += 0.05
    stale_rev = session.mode_revision - 1
    cue = _cue(
        "Sarah, come up.",
        temporal=TemporalIntent.NOW, targets=["sarah"],
        scope=Scope.SINGLE, mode_rev=stale_rev,
        utt_id="utt-4", at=t,
    )
    d = session.on_cue(cue, _cams(), t, role_based=True, role_map=ROLE_MAP)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=cue,
        cameras_considered=_considered(_cams(), d.camera_id),
        latencies_ms={"asr": 305, "cue": 5200, "decide": 0, "total": 5505},
        source="FIXTURE",
    ))

    # Step 6: RESUME_AUTO, then correction utterance
    t += 1.0
    d = session.on_manual("RESUME_AUTO", t)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=None,
        cameras_considered=[], latencies_ms={"decide": 0, "total": 0},
        source="FIXTURE",
    ))

    t += 2.6
    # Correction: assembler combined both halves into one final utterance;
    # the parser returns only the corrected final target.
    cue = _cue(
        "Please welcome Sarah... actually, Daniel.",
        temporal=TemporalIntent.NOW, targets=["daniel"],
        scope=Scope.SINGLE, mode_rev=session.mode_revision,
        utt_id="utt-5", at=t,
    )
    d = session.on_cue(cue, _cams(), t, role_based=True, role_map=ROLE_MAP)
    _emit(logger, record_from_session_decision(
        d, at=t, cue=cue,
        cameras_considered=_considered(_cams(), d.camera_id),
        latencies_ms={"asr": 340, "cue": 890, "decide": 1, "total": 1231},
        source="FIXTURE",
    ))
    session.on_ack(d.decision_seq, applied=True, now=t + 0.05)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="C-lane fixture replay.")
    ap.add_argument("--out", metavar="PATH",
                    help="append JSON Lines to this file in addition to stdout.")
    args = ap.parse_args(argv)
    logger = DecisionLogger(args.out) if args.out else None
    # Deliberately do not consult wall time; each record's `at` field is
    # scripted so replays are byte-identical.
    _ = time  # keep import intentional (available for callers who want live wall time)
    return run(logger=logger)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
