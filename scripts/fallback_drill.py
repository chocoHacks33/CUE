"""Walk the operator through the demo fallback ladder and confirm the
observed state after each simulated outage.

Never edits any real config. Simulated outages are injected as
environment flags so downstream code can honour them:

    CUE_SIMULATE_OPENAI_DOWN=1     -> semantic parser must safe-HOLD
    CUE_SIMULATE_DEEPGRAM_DOWN=1   -> ASR bridge must degrade to manual
    CUE_SIMULATE_ALL_DOWN=1        -> switch to the fixture timeline

The drill prints each state, prompts the operator to press <Enter> to
confirm what they see on the desk, and writes a short log to
``docs/results/C-stage7-fallback.md``.

Nothing here starts the desk; it is a checklist runner. Start the desk
in another terminal before you run this.

Usage
-----
    python scripts/fallback_drill.py
    python scripts/fallback_drill.py --dry-run   # just print, no prompts
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


LADDER: list[dict] = [
    {
        "id": "openai-down",
        "flag": "CUE_SIMULATE_OPENAI_DOWN",
        "title": "Semantic engine down (OpenAI 5xx or rate-limited)",
        "what_the_desk_should_show": [
            "Header banner: ASSIST mode.",
            "Understood card: 'semantic engine unavailable — HOLD'.",
            "Suggestion strip: taps `1/2/3` accept a suggested cut.",
            "Decisions log: no auto TAKE lines during the outage.",
        ],
        "operator_line": (
            "Semantic engine is down. I'm running in ASSIST mode. Every "
            "cut is confirmed by me."
        ),
        "confirmation_prompt": (
            "Confirm you can see the ASSIST banner and the 'semantic "
            "engine unavailable' Understood card, then press <Enter>."
        ),
    },
    {
        "id": "deepgram-down",
        "flag": "CUE_SIMULATE_DEEPGRAM_DOWN",
        "title": "ASR down (Deepgram unreachable)",
        "what_the_desk_should_show": [
            "Header banner: red alarm 'CAPTIONS OFF - manual only'.",
            "Deepgram raw feed: stopped, last line flagged as stale.",
            "Suggestion strip: cleared; no automatic suggestions.",
            "Decisions log: only manual TAKE (1/2/3), HOLD (H), AUTO (A).",
        ],
        "operator_line": "ASR is down; I'll switch by hand.",
        "confirmation_prompt": (
            "Confirm the red CAPTIONS OFF alarm is visible and the "
            "Deepgram feed shows STALE, then press <Enter>."
        ),
    },
    {
        "id": "all-down",
        "flag": "CUE_SIMULATE_ALL_DOWN",
        "title": "Everything down — fixture timeline",
        "what_the_desk_should_show": [
            "Header chip: 'FIXTURE' (yellow).",
            "Every decision line stamped `source=FIXTURE`.",
            "Understood card: sourced from scripts/fixture_cues.py, not "
            "a live model.",
        ],
        "operator_line": (
            "This is a scripted timeline, marked FIXTURE on screen."
        ),
        "confirmation_prompt": (
            "Confirm the FIXTURE chip is visible in the header and "
            "the source field on the decision lines reads FIXTURE, "
            "then press <Enter>."
        ),
    },
]


@dataclass
class StepResult:
    id: str
    title: str
    ok: bool = False
    notes: list[str] = field(default_factory=list)


def _print_step(step: dict) -> None:
    print("\n" + "=" * 72, flush=True)
    print(step["title"], flush=True)
    print("=" * 72, flush=True)
    print(f"Simulated with:  export {step['flag']}=1", flush=True)
    print("Say this out loud:", flush=True)
    print(f'    "{step["operator_line"]}"', flush=True)
    print("What the desk should show:", flush=True)
    for line in step["what_the_desk_should_show"]:
        print(f"  - {line}", flush=True)


def _confirm(prompt: str, *, dry_run: bool) -> bool:
    if dry_run:
        print(f"[dry-run] would prompt: {prompt}", flush=True)
        return True
    print(f"\n>>> {prompt}", flush=True)
    try:
        raw = input("Type 'y' to confirm, anything else to mark NOT SEEN: ")
    except EOFError:
        return False
    return raw.strip().lower().startswith("y")


def write_report(results: list[StepResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# C-lane · Stage 7 fallback drill",
        "",
        f"_Ran at {time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())} UTC._",
        "",
        "| Rung | Confirmed on desk? |",
        "|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.title} | {'yes' if r.ok else 'no'} |")
    lines.append("")
    for r in results:
        lines += [f"## {r.title}", ""]
        lines += [f"- confirmed: **{'yes' if r.ok else 'no'}**"]
        for note in r.notes:
            lines.append(f"- {note}")
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="CUE demo fallback drill.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the ladder without prompting.")
    args = ap.parse_args(argv)

    if not args.dry_run:
        print(
            "This drill assumes the desk is already running in another "
            "terminal. Start it with:\n"
            "  apps/api/.venv/Scripts/python.exe prototypes/desk/server.py "
            "--source mic --model flux-general-en\n"
            "Then flip each simulate flag on / off between rungs.",
            flush=True,
        )

    results: list[StepResult] = []
    for step in LADDER:
        _print_step(step)
        ok = _confirm(step["confirmation_prompt"], dry_run=args.dry_run)
        r = StepResult(id=step["id"], title=step["title"], ok=ok)
        if not ok:
            r.notes.append("Operator did not confirm. Debug before demo.")
        results.append(r)

    out = REPO_ROOT / "docs" / "results" / "C-stage7-fallback.md"
    write_report(results, out)
    print(f"\nWrote {out}", flush=True)

    # Never fails the script — the drill is a checklist, not a gate.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
