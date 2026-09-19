"""Aggregate the C-lane latency trace from a DecisionLogger JSON Lines file.

Each line is a DecisionRecord. Its ``latencies_ms`` map carries per-hop
latencies stamped by LiveLane:

    final_ms       Deepgram: audio_seconds_sent - last_word.end
                   (audio-time latency of a final Results message)
    cue_decide_ms  Wall-clock: parse(final) + DirectorSession.on_cue
                   (single hop combining semantic + policy)
    ack_ms         Wall-clock: emit -> compositor ACK (D)
                   Not stamped by LiveLane; computed here from a
                   separate ACK log if provided.
    total_ms       Sum of the three hops if all present.

Usage::

    python scripts/latency_report.py path/to/decisions.jsonl
    python scripts/latency_report.py decisions.jsonl --acks acks.jsonl

ACK log line shape (any of these keys works)::

    {"decision_seq": 3, "applied": true, "at_monotonic_s": 12.345}
    {"decisionSeq": 3, "applied": true, "atMs": 12345}
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HOPS = ("final_ms", "cue_decide_ms", "ack_ms", "total_ms")


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _index_acks(acks: list[dict]) -> dict[int, float]:
    """Map decision_seq -> at_monotonic_s (seconds)."""
    out: dict[int, float] = {}
    for a in acks:
        seq = a.get("decision_seq") or a.get("decisionSeq")
        if seq is None:
            continue
        at = a.get("at_monotonic_s")
        if at is None and "atMs" in a:
            at = a["atMs"] / 1000
        if at is not None:
            out[int(seq)] = float(at)
    return out


def _at_seconds(record: dict) -> float | None:
    v = record.get("at")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _percentiles(xs: list[float]) -> dict[str, float | None]:
    if not xs:
        return {"p50": None, "p95": None, "count": 0}
    s = sorted(xs)
    return {
        "count": len(s),
        "p50": round(statistics.median(s), 1),
        "p95": round(s[int(0.95 * (len(s) - 1))], 1),
    }


def aggregate(
    decisions: list[dict], acks_by_seq: dict[int, float] | None = None,
) -> dict[str, dict]:
    samples: dict[str, list[float]] = {h: [] for h in HOPS}
    for rec in decisions:
        lm = rec.get("latencies_ms") or {}
        total: float = 0.0
        have_any = False
        for hop in ("final_ms", "cue_decide_ms"):
            v = lm.get(hop)
            if isinstance(v, (int, float)) and v >= 0:
                samples[hop].append(float(v))
                total += float(v)
                have_any = True
        seq = rec.get("decision_seq")
        if acks_by_seq and seq is not None and int(seq) in acks_by_seq:
            emit_at = _at_seconds(rec)
            ack_at = acks_by_seq[int(seq)]
            if emit_at is not None and ack_at >= emit_at:
                ack_ms = (ack_at - emit_at) * 1000
                samples["ack_ms"].append(ack_ms)
                total += ack_ms
                have_any = True
        if have_any:
            samples["total_ms"].append(total)
    return {hop: _percentiles(samples[hop]) for hop in HOPS}


def _print(summary: dict[str, dict]) -> None:
    print(f"{'hop':<15} {'n':>4} {'p50':>8} {'p95':>8}")
    print(f"{'-' * 15} {'-' * 4} {'-' * 8} {'-' * 8}")
    for hop, s in summary.items():
        n = s.get("count") or 0
        p50 = s.get("p50")
        p95 = s.get("p95")
        p50_s = f"{p50:.1f}" if isinstance(p50, (int, float)) else "-"
        p95_s = f"{p95:.1f}" if isinstance(p95, (int, float)) else "-"
        print(f"{hop:<15} {n:>4} {p50_s:>8} {p95_s:>8}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="C-lane latency report.")
    ap.add_argument("decisions", type=Path,
                    help="path to a JSONL decision log")
    ap.add_argument("--acks", type=Path, default=None,
                    help="optional JSONL ACK log; enables ack_ms + total_ms")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON summary")
    args = ap.parse_args(argv)

    decisions = _read_jsonl(args.decisions)
    acks_map = _index_acks(_read_jsonl(args.acks)) if args.acks else None
    summary = aggregate(decisions, acks_map)

    if args.json:
        print(json.dumps({"decisions": len(decisions),
                          "acks": len(acks_map or {}),
                          "hops": summary}, indent=2))
    else:
        print(f"# decisions: {len(decisions)}  "
              f"acks: {len(acks_map or {})}")
        _print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
