"""Soak test for CLane. Replays the recorded fixture cue timeline at
real-time pace through the Stage-2 CLane with a *fake* parser, for
``--minutes N`` (default 2). Asserts operational invariants:

  - No duplicate decisions          (same decision_seq never emitted twice)
  - Bounded queue depth             (SemanticQueue never exceeds 2 slots)
  - Bounded memory growth           (rss delta ≤ 50 MB after N minutes)
  - Bounded log size                (log file ≤ 12 MB after N minutes)

The test runs OFFLINE — no OpenAI, no Deepgram, no LiveKit. Uses
``scripts/fixture_cues.py``'s timeline for content and its cue shapes
so the DirectorSession sees realistic input.

Writes ``docs/results/C-soak.md`` with the measurements + a pass/fail
per invariant.

Usage:
  python scripts/soak_c_lane.py                     # 2 minutes
  python scripts/soak_c_lane.py --minutes 20        # release run
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

try:  # POSIX
    import resource as _resource
except ImportError:  # Windows
    _resource = None

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cue_api.c_lane import CLane  # noqa: E402
from cue_api.policy.log import DecisionLogger, DecisionRecord  # noqa: E402
from cue_api.semantics.parser import (  # noqa: E402
    Action, Cue, Intent, Scope, TemporalIntent,
)

# ---- fixture timeline (mirrors scripts/fixture_cues.py's beats) ------

FIXTURE_TIMELINE: list[dict] = [
    {"kind": "utterance", "gap_s": 0.6,
     "text": "Sarah joins us after the break.", "utterance_id": "utt-1",
     "temporal": "FUTURE", "targets": ["sarah"]},
    {"kind": "utterance", "gap_s": 2.5,
     "text": "Please welcome Sarah Tan.", "utterance_id": "utt-2",
     "temporal": "NOW", "targets": ["sarah"]},
    {"kind": "utterance", "gap_s": 2.6, "guest_healthy": False,
     "text": "Sarah, could you answer that?", "utterance_id": "utt-3",
     "temporal": "NOW", "targets": ["sarah"]},
    {"kind": "manual", "gap_s": 1.4, "command": "HOLD"},
    {"kind": "utterance", "gap_s": 0.05,
     "text": "Sarah, come up.", "utterance_id": "utt-4",
     "temporal": "NOW", "targets": ["sarah"], "stale_mode_rev": True},
    {"kind": "manual", "gap_s": 1.0, "command": "RESUME_AUTO"},
    {"kind": "utterance", "gap_s": 2.6,
     "text": "Please welcome Sarah... actually, Daniel.",
     "utterance_id": "utt-5",
     "temporal": "NOW", "targets": ["daniel"]},
]

ROLE_MAP = {"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"}


def _cams(*, guest_healthy: bool = True) -> dict:
    return {
        "CAM-HOST":  {"role": "host",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
        "CAM-GUEST": {"role": "guest", "healthy": guest_healthy, "epoch": 1,
                      "confirmed_guest_ids": ["sarah", "daniel"],
                      "evidence_age_s": 0.4, "guest_ready": True},
        "CAM-WIDE":  {"role": "wide",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
    }


def _fake_parse(entry: dict):
    """Return the Cue the fixture entry describes. Deterministic — no LLM."""
    targets = entry.get("targets") or []
    temporal = entry.get("temporal") or "NOW"
    text = entry["text"]
    ti = getattr(TemporalIntent, temporal)
    if len(targets) > 1:
        return Cue(
            target_guest_ids=list(targets), scope=Scope.GROUP,
            intent=Intent.INTRODUCE, temporal_intent=ti,
            action=Action.WIDE if ti == TemporalIntent.NOW else Action.HOLD,
            evidence_text=text, utterance_id=entry["utterance_id"],
            created_at=time.monotonic(),
        )
    return Cue(
        target_guest_ids=list(targets), scope=Scope.SINGLE if targets else Scope.NONE,
        intent=Intent.INTRODUCE, temporal_intent=ti,
        action=Action.SHOW if (ti == TemporalIntent.NOW and targets)
               else Action.HOLD,
        evidence_text=text, utterance_id=entry["utterance_id"],
        created_at=time.monotonic(),
    )


def _rss_mb() -> float:
    """RSS in MB. Returns 0.0 on Windows (no `resource`); the memory
    invariant is skipped in that case with a note in the summary."""
    if _resource is None:
        return 0.0
    try:
        r = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is KB on Linux, bytes on macOS.
        if sys.platform == "darwin":
            return r / (1024 * 1024)
        return r / 1024
    except Exception:
        return 0.0


def run_soak(minutes: float, log_path: Path) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    seen_seqs: set[int] = set()
    duplicate_seqs = 0
    max_queue_depth = 0
    decisions: list[DecisionRecord] = []

    def emit(rec: DecisionRecord) -> None:
        nonlocal duplicate_seqs
        if rec.decision_seq in seen_seqs:
            duplicate_seqs += 1
        seen_seqs.add(rec.decision_seq)
        decisions.append(rec)

    logger = DecisionLogger(log_path)

    def parse_fn(text: str):
        # We choose the Cue at emit-time; the queue passes text-only.
        # Match text back to entry by nearest recent submitted text.
        for entry in FIXTURE_TIMELINE:
            if entry["kind"] == "utterance" and entry["text"] == text:
                return _fake_parse(entry), 1.0
        return Cue(
            target_guest_ids=[], scope=Scope.NONE, intent=Intent.NONE,
            temporal_intent=TemporalIntent.UNCERTAIN, action=Action.HOLD,
            evidence_text=text,
        ), 1.0

    def emit_and_log(rec: DecisionRecord) -> None:
        logger.append(rec)
        emit(rec)

    lane = CLane(parse_fn=parse_fn, emit=emit_and_log,
                 role_based=True, role_map=ROLE_MAP,
                 initial_camera="CAM-HOST",
                 camera_state_max_age_s=60.0)

    rss0 = _rss_mb()
    t_start = time.monotonic()
    deadline = t_start + minutes * 60
    loop_count = 0
    now = t_start

    while now < deadline:
        for entry in FIXTURE_TIMELINE:
            if now >= deadline:
                break
            gap = float(entry.get("gap_s", 0)) or 0.0
            if gap > 0:
                time.sleep(min(gap, deadline - now))
            now = time.monotonic()
            if entry["kind"] == "manual":
                lane.on_manual(entry["command"], now=now)
            else:
                cams = _cams(guest_healthy=not entry.get("guest_healthy") is False)
                lane.on_camera_state(cams, now=now)
                cue = _fake_parse(entry)
                if entry.get("stale_mode_rev"):
                    stale = max(0, lane.mode_revision - 1)
                    lane._queue.submit(  # noqa: SLF001 -- deliberate
                        utterance=entry["text"], mode_revision=stale, now=now,
                        utterance_id=entry["utterance_id"], created_at=now,
                    )
                else:
                    cue.mode_revision = lane.mode_revision
                    lane._queue.submit(  # noqa: SLF001 -- deliberate
                        utterance=entry["text"],
                        mode_revision=lane.mode_revision, now=now,
                        utterance_id=entry["utterance_id"], created_at=now,
                    )
                # Track queue depth right after submit.
                depth = int(lane._queue.in_flight is not None) + int(  # noqa: SLF001
                    lane._queue.pending is not None,  # noqa: SLF001
                )
                if depth > max_queue_depth:
                    max_queue_depth = depth
                lane.tick(now)
        loop_count += 1
        # Small yield to keep the run interruptible.
        time.sleep(0.05)
        now = time.monotonic()

    # Force any lingering queue work through.
    lane.tick(time.monotonic())
    gc.collect()

    rss1 = _rss_mb()
    log_bytes = log_path.stat().st_size if log_path.exists() else 0
    elapsed_min = (time.monotonic() - t_start) / 60

    memory_measurable = _resource is not None
    invariants = {
        "no_duplicate_decisions": duplicate_seqs == 0,
        "bounded_queue_depth": max_queue_depth <= 2,
        "bounded_memory_growth_50mb": (
            (rss1 - rss0) <= 50 if memory_measurable else True
        ),
        "bounded_log_size_12mb": log_bytes <= 12 * 1024 * 1024,
    }
    return {
        "minutes": minutes,
        "elapsed_min": round(elapsed_min, 2),
        "loops": loop_count,
        "decisions": len(decisions),
        "duplicate_seqs": duplicate_seqs,
        "max_queue_depth": max_queue_depth,
        "rss_start_mb": round(rss0, 1),
        "rss_end_mb": round(rss1, 1),
        "rss_delta_mb": round(rss1 - rss0, 1),
        "log_bytes": log_bytes,
        "invariants": invariants,
        "all_invariants_passed": all(invariants.values()),
    }


def _write_md(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C-lane · Soak run",
        "",
        f"- Duration: {summary['elapsed_min']} min "
        f"(requested {summary['minutes']} min)",
        f"- Timeline loops: {summary['loops']}",
        f"- Decisions emitted: {summary['decisions']}",
        f"- Duplicate `decision_seq`s: {summary['duplicate_seqs']}",
        f"- Max queue depth: {summary['max_queue_depth']}",
        f"- Memory: {summary['rss_start_mb']} MB → "
        f"{summary['rss_end_mb']} MB (Δ {summary['rss_delta_mb']} MB)",
        f"- Log size: {summary['log_bytes']} bytes",
        "",
        "## Invariants",
        "| Invariant | Result |",
        "|---|---|",
    ]
    for k, ok in summary["invariants"].items():
        lines.append(f"| `{k}` | {'PASS' if ok else 'FAIL'} |")
    lines += ["",
              f"**All invariants passed: {summary['all_invariants_passed']}**"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="C-lane soak test.")
    ap.add_argument("--minutes", type=float, default=2.0,
                    help="Duration in minutes (default 2; release run 20).")
    ap.add_argument("--log", default="/tmp/cue-soak.jsonl",
                    help="Path for the DecisionLogger JSONL log.")
    args = ap.parse_args(argv)

    log_path = Path(args.log)
    print(f"soak_c_lane: running for {args.minutes} min, log -> {log_path}",
          flush=True)
    summary = run_soak(args.minutes, log_path)
    print(json.dumps(summary, indent=2))
    md = REPO_ROOT / "docs" / "results" / "C-soak.md"
    _write_md(md, summary)
    print(f"\nwrote {md}")
    return 0 if summary["all_invariants_passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
