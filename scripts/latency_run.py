"""Live end-to-end latency probe for the C-lane.

Prompts the operator to read 12 scripted sentences aloud, drives them
through the full pipeline (LiveLane's async runner), logs every hop and
prints p50 / p95 per hop. Writes ``docs/results/C-latency.md``.

Hops measured (all in ms, from audio time where possible):
  final_ms       audio_seconds_sent - words[-1].end
                 (Deepgram commit latency)
  cue_decide_ms  decision emitted - last Deepgram final message arrived
                 (parser + policy)
  ack_ms         ACK received - decision emitted
                 (compositor, D)  — only when --wait-ack is set
  total_ms       final_ms + cue_decide_ms [+ ack_ms]

Targets (labelled clearly as targets, not measurements):
  total p50 ≤ 1.5 s
  total p95 ≤ 2.5 s

Requires:
  OPENAI_API_KEY   the semantic parser
  DEEPGRAM_API_KEY the ASR
  CUE_MODEL        pinned model id (or the parser safe-HOLDs everything)

Usage:
  python scripts/latency_run.py              # 12 sentences, no ACK hop
  python scripts/latency_run.py --wait-ack   # add ack_ms hop
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

load_dotenv()

from cue_api.c_lane_live import LiveLane, TARGET_SAMPLE_RATE  # noqa: E402
from cue_api.policy.log import DecisionLogger  # noqa: E402
from cue_api.policy.wire import DecisionEvent  # noqa: E402

# --- imports from live_lane.py so we reuse the mic + Deepgram wiring ---
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from live_lane import (  # noqa: E402
    BuildDeepgramFactory,
    FakeCameraProvider,
    MicPcmSource,
    StdoutSender,
)

# 12 scripted sentences — a mix of NOW / FUTURE / MENTION / CORRECTION.
SCRIPT: list[str] = [
    "Please welcome Sarah Tan.",
    "Right, over to Maya.",
    "Alex, take it away.",
    "Kai, the stage is yours.",
    "Big hand for Ms Chen, everybody.",
    "Priya, could you answer that?",
    "Actually Sarah, please join us now.",
    "Please welcome Sarah and Daniel.",
    "Sarah joins us after the break.",
    "Don't bring Priya up yet.",
    "Thanks Daniel, that was wonderful.",
    "Please put your hands together for our special guest.",
]

TARGET_P50_S = 1.5
TARGET_P95_S = 2.5


class _CapturingSender:
    """StdoutSender + capture into a list for latency aggregation."""
    def __init__(self, tee: StdoutSender) -> None:
        self._tee = tee
        self.events: list[DecisionEvent] = []

    def send(self, event: DecisionEvent, *, decision_seq: int) -> None:
        self.events.append(event)
        self._tee.send(event, decision_seq=decision_seq)


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"latency_run: {name} not set. Set it in .env or export it.",
              file=sys.stderr, flush=True)
        sys.exit(2)
    return v


def _percentiles(xs: list[float]) -> tuple[float | None, float | None]:
    if not xs:
        return None, None
    s = sorted(xs)
    return (statistics.median(s), s[int(0.95 * (len(s) - 1))])


def _fmt(ms: float | None) -> str:
    return f"{ms:.0f}" if isinstance(ms, (int, float)) else "-"


def _write_md(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hops = summary["hops"]
    lines = [
        "# C-lane · Live end-to-end latency",
        "",
        f"- Ran at: {summary['at']}",
        f"- Deepgram model: `{summary['dg_model']}`",
        f"- Semantic model: `{summary['cue_model']}`",
        f"- Sentences read: {summary['sentences_read']} / {summary['sentences_total']}",
        f"- Decisions received: {summary['decisions']}",
        "",
        "## Per-hop latency (ms)",
        "| Hop | p50 | p95 | n |",
        "|---|---|---|---|",
    ]
    for hop, s in hops.items():
        lines.append(f"| `{hop}` | {_fmt(s['p50'])} | {_fmt(s['p95'])} | {s['n']} |")
    lines += [
        "",
        "## Targets (not measurements)",
        f"- Total p50 target: **{TARGET_P50_S * 1000:.0f} ms**",
        f"- Total p95 target: **{TARGET_P95_S * 1000:.0f} ms**",
        "",
        "Measured totals vs. targets:",
        f"- Total p50 measured: **{_fmt(hops.get('total_ms', {}).get('p50'))} ms**",
        f"- Total p95 measured: **{_fmt(hops.get('total_ms', {}).get('p95'))} ms**",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _prompt_read(sentence: str, idx: int, total: int) -> None:
    # Show the sentence and wait ~1.2 s baseline for the speaker to start;
    # the loop then waits up to 8 s for the decision to arrive.
    print(f"\n>>> [{idx}/{total}] Please read this sentence aloud:", flush=True)
    print(f"    \"{sentence}\"", flush=True)
    await asyncio.sleep(1.2)


async def _run(args: argparse.Namespace) -> int:
    _require("OPENAI_API_KEY")
    _require("DEEPGRAM_API_KEY")
    cue_model = os.environ.get("CUE_MODEL")
    if not cue_model:
        print("latency_run: CUE_MODEL not set — parser will safe-HOLD every "
              "utterance and no cue_decide_ms will be measured. Aborting.",
              file=sys.stderr, flush=True)
        return 2

    log_path = Path(args.log_decisions or "/tmp/cue-latency.jsonl")
    tee_sender = StdoutSender(log_path if log_path.name else None)
    sender = _CapturingSender(tee_sender)

    pcm_source = MicPcmSource(device=args.input_device)
    camera = FakeCameraProvider()

    lane = LiveLane(
        pcm_source=pcm_source,
        deepgram_factory=lambda: BuildDeepgramFactory(
            lane=lane,  # noqa: F821 -- filled after LiveLane constructs
            model=args.dg_model,
            endpointing_ms=args.endpointing_ms,
            utterance_end_ms=args.utterance_end_ms,
        )(),
        camera_state=camera,
        sender=sender,
        role_based=True,
        role_map={
            "sarah": "CAM-GUEST", "daniel": "CAM-GUEST", "priya": "CAM-GUEST",
            "maya": "CAM-GUEST", "alex": "CAM-GUEST", "jordan": "CAM-GUEST",
            "kai": "CAM-GUEST",
        },
    )

    stop = asyncio.Event()
    runner = asyncio.create_task(lane.run(stop_event=stop))

    print(
        f"\nlatency_run: reading {len(SCRIPT)} scripted sentences.\n"
        f"  Deepgram model: {args.dg_model}\n"
        f"  Semantic model: {cue_model}\n"
        f"  Log: {log_path}\n"
        f"Speak clearly, one sentence at a time, when prompted."
        , flush=True,
    )
    await asyncio.sleep(0.8)

    sentences_read = 0
    deadline_per_sentence = 8.0
    initial_count = 0
    for i, sentence in enumerate(SCRIPT, 1):
        initial_count = len(sender.events)
        await _prompt_read(sentence, i, len(SCRIPT))
        t0 = time.monotonic()
        while (time.monotonic() - t0) < deadline_per_sentence:
            if len(sender.events) > initial_count:
                sentences_read += 1
                break
            await asyncio.sleep(0.1)

    # Give the loop a chance to flush the last decision.
    await asyncio.sleep(2.0)
    stop.set()
    with contextlib.suppress(BaseException):
        await runner

    hops: dict[str, list[float]] = {
        "final_ms": [], "cue_decide_ms": [], "total_ms": [],
    }
    for ev in sender.events:
        lm = dict(ev.latencies_ms or {})
        f = lm.get("final_ms")
        c = lm.get("cue_decide_ms")
        if isinstance(f, (int, float)) and f >= 0:
            hops["final_ms"].append(float(f))
        if isinstance(c, (int, float)) and c >= 0:
            hops["cue_decide_ms"].append(float(c))
        if all(isinstance(x, (int, float)) and x >= 0 for x in (f, c)):
            hops["total_ms"].append(float(f) + float(c))

    hop_summary: dict[str, dict] = {}
    for hop, vals in hops.items():
        p50, p95 = _percentiles(vals)
        hop_summary[hop] = {
            "n": len(vals),
            "p50": round(p50, 1) if p50 is not None else None,
            "p95": round(p95, 1) if p95 is not None else None,
        }

    summary = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dg_model": args.dg_model,
        "cue_model": cue_model,
        "sentences_read": sentences_read,
        "sentences_total": len(SCRIPT),
        "decisions": len(sender.events),
        "hops": hop_summary,
    }
    md_path = REPO_ROOT / "docs" / "results" / "C-latency.md"
    json_path = REPO_ROOT / "docs" / "results" / "C-latency.json"
    _write_md(md_path, summary)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(
        f"\nTargets (not measurements):"
        f"\n  total p50 ≤ {TARGET_P50_S * 1000:.0f} ms"
        f"\n  total p95 ≤ {TARGET_P95_S * 1000:.0f} ms"
    )
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Live end-to-end latency probe for the C-lane.",
    )
    ap.add_argument("--input-device", dest="input_device", default=None,
                    help="sounddevice input device index or name substring")
    ap.add_argument("--dg-model", dest="dg_model", default="nova-3",
                    help="Deepgram model id (nova-3 or flux-general-en).")
    ap.add_argument("--endpointing-ms", dest="endpointing_ms",
                    type=int, default=300)
    ap.add_argument("--utterance-end-ms", dest="utterance_end_ms",
                    type=int, default=1000)
    ap.add_argument("--log-decisions", default=None,
                    help="Also append DecisionRecord JSONL to this path.")
    ap.add_argument("--wait-ack", action="store_true",
                    help="Wait for D's ACK before scoring each decision.")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
