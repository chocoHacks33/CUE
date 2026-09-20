"""Release evaluation for CUE's semantic parser.

Runs the dev set, then the 40-case held-out set. Records:
- git commit
- pinned model id (from CUE_MODEL)
- SHA-256 of the exact SYSTEM prompt template used
- pass rate, wrong SHOW cuts, per-category counts
- p50 / p95 latency (ms)

Held-out guard: every held-out run is appended to
``docs/results/heldout_runs.jsonl``. If the SYSTEM prompt hash has
changed since the last held-out run and ``--acknowledge-retune`` was
NOT passed, the tool refuses. The held-out set is a *measurement*
instrument, not a tuning input.

Requires two secrets. Missing either exits **2** with a clear message
and NO evaluation run:
  OPENAI_API_KEY   the semantic parser
  CUE_MODEL        the pinned model id (never a silent default)

Writes:
  docs/results/C-release-eval.md   (human-readable summary)
  docs/results/C-release-eval.json (machine-readable summary)
  docs/results/heldout_runs.jsonl  (append-only ledger)

Usage:
  python scripts/release_eval.py
  python scripts/release_eval.py --acknowledge-retune   # only after prompt change
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

DATA_DIR = REPO_ROOT / "scripts" / "data"
RESULTS_DIR = REPO_ROOT / "docs" / "results"
LEDGER = RESULTS_DIR / "heldout_runs.jsonl"


def _die(message: str, *, code: int = 2) -> None:
    print(f"release_eval: {message}", file=sys.stderr, flush=True)
    sys.exit(code)


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        _die(f"{name} not set. Set it in .env or export it before running.")
    return v


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return out
    except Exception:
        return "unknown"


def _system_prompt_hash() -> tuple[str, str]:
    """SHA-256 of the raw SYSTEM template. Returns (hash, prompt_source_path)."""
    from cue_api.semantics.parser import SYSTEM
    h = hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()
    return h, "cue_api.semantics.parser.SYSTEM"


def _load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return data.get("cases", []) if isinstance(data, dict) else data


def _check(case: dict, cue) -> bool:
    if cue.action.value not in case["action"]:
        return False
    if cue.action.value == "SHOW" and "target_guest_ids" in case:
        return sorted(cue.target_guest_ids) == sorted(case["target_guest_ids"])
    return True


def _run_set(cases: list[dict], model: str, label: str) -> dict:
    from cue_api.semantics.parser import ProgrammeContext, parse
    rows: list[dict] = []
    latencies: list[float] = []
    wrong_cuts_by_cat: Counter[str] = Counter()
    passes_by_cat: Counter[str] = Counter()
    total_by_cat: Counter[str] = Counter()

    for i, case in enumerate(cases, 1):
        programme = None
        if case.get("programme"):
            programme = ProgrammeContext(**case["programme"])
        cue, ms = parse(
            case["say"], model=model,
            programme=programme, roster=case.get("roster"),
            context=case.get("context") or "",
        )
        ok = _check(case, cue)
        wrong_cut = (not ok) and cue.action.value == "SHOW"
        rows.append({
            "id": case["id"], "cat": case["cat"], "say": case["say"],
            "expected": case["action"], "got": cue.model_dump(mode="json"),
            "ok": ok, "wrong_cut": wrong_cut, "ms": round(ms),
        })
        latencies.append(ms)
        total_by_cat[case["cat"]] += 1
        if ok:
            passes_by_cat[case["cat"]] += 1
        if wrong_cut:
            wrong_cuts_by_cat[case["cat"]] += 1
        print(
            f"{label} {i:>3}/{len(cases)}  "
            f"{'PASS' if ok else ('WRONG_CUT' if wrong_cut else 'FAIL'):>9}  "
            f"{case['id']:<16} {ms:5.0f}ms  "
            f"{cue.action.value:<5} {cue.target_guest_ids}",
            flush=True,
        )

    latencies_sorted = sorted(latencies)
    p50 = round(statistics.median(latencies_sorted)) if latencies_sorted else 0
    p95 = (
        round(latencies_sorted[int(0.95 * (len(latencies_sorted) - 1))])
        if latencies_sorted else 0
    )
    return {
        "label": label,
        "cases": len(rows),
        "passed": sum(r["ok"] for r in rows),
        "pass_rate": round(sum(r["ok"] for r in rows) / len(rows), 3)
                     if rows else 0.0,
        "wrong_cuts": sum(r["wrong_cut"] for r in rows),
        "wrong_cuts_by_cat": dict(wrong_cuts_by_cat),
        "passes_by_cat": dict(passes_by_cat),
        "total_by_cat": dict(total_by_cat),
        "p50_ms": p50, "p95_ms": p95,
        "rows": rows,
    }


def _last_heldout_hash() -> str | None:
    if not LEDGER.exists():
        return None
    last = None
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return (last or {}).get("prompt_hash")


def _append_ledger(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def _write_md(summary: dict, path: Path) -> None:
    dev = summary["dev"]
    hel = summary["heldout"]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C-lane · Release evaluation",
        "",
        f"- Git commit: `{summary['git_commit']}`",
        f"- Model: `{summary['model']}`",
        f"- System-prompt SHA-256: `{summary['prompt_hash']}`",
        f"- Ran at: {summary['at']}",
        (f"- **Retune acknowledged: {summary['acknowledged_retune']}**"
         if summary['acknowledged_retune'] else ""),
        "",
        "## Dev set",
        f"- Cases: {dev['cases']}",
        f"- Pass rate: **{dev['pass_rate']:.1%}**  (target ≥ 90% on dev)",
        f"- Wrong SHOW cuts: **{dev['wrong_cuts']}**  (target 0)",
        f"- p50 latency: **{dev['p50_ms']} ms**",
        f"- p95 latency: **{dev['p95_ms']} ms**",
        "",
        "### Dev per-category",
        "| Category | Passed / Total | Wrong cuts |",
        "|---|---|---|",
    ]
    for cat, total in sorted(dev["total_by_cat"].items()):
        passed = dev["passes_by_cat"].get(cat, 0)
        wc = dev["wrong_cuts_by_cat"].get(cat, 0)
        lines.append(f"| {cat} | {passed} / {total} | {wc} |")

    lines += [
        "",
        "## Held-out set (release gate — never tuned against)",
        f"- Cases: {hel['cases']}",
        f"- Pass rate: **{hel['pass_rate']:.1%}**  (target ≥ 90%)",
        f"- Wrong SHOW cuts: **{hel['wrong_cuts']}**  (release gate: 0)",
        f"- p50 latency: **{hel['p50_ms']} ms**",
        f"- p95 latency: **{hel['p95_ms']} ms**",
        "",
        "### Held-out per-category",
        "| Category | Passed / Total | Wrong cuts |",
        "|---|---|---|",
    ]
    for cat, total in sorted(hel["total_by_cat"].items()):
        passed = hel["passes_by_cat"].get(cat, 0)
        wc = hel["wrong_cuts_by_cat"].get(cat, 0)
        lines.append(f"| {cat} | {passed} / {total} | {wc} |")

    lines += [
        "",
        "## Release gate",
        (
            "- **AUTO cuts allowed**: 0 wrong held-out cuts AND held-out pass "
            "≥ 90% AND total p95 ≤ 2.5 s. See `C-scope-decision.md` for the "
            "final decision using measured live latency."
        ),
    ]
    path.write_text("\n".join(line for line in lines if line is not None) + "\n",
                    encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="C-lane release evaluation.")
    ap.add_argument(
        "--acknowledge-retune", action="store_true",
        help="Acknowledge that the SYSTEM prompt changed. Required after "
             "any prompt edit; recorded in the ledger.",
    )
    args = ap.parse_args(argv)

    _require_env("OPENAI_API_KEY")
    model = _require_env("CUE_MODEL")

    dev_path = DATA_DIR / "adversarial.json"
    heldout_path = DATA_DIR / "heldout.json"
    if not dev_path.exists() or not heldout_path.exists():
        _die(f"missing dataset(s): {dev_path.name} / {heldout_path.name}")

    prompt_hash, prompt_source = _system_prompt_hash()
    last_heldout_hash = _last_heldout_hash()
    prompt_changed = (
        last_heldout_hash is not None and last_heldout_hash != prompt_hash
    )
    if prompt_changed and not args.acknowledge_retune:
        _die(
            "the SYSTEM prompt hash has changed since the last held-out run.\n"
            f"  previous hash: {last_heldout_hash}\n"
            f"  current  hash: {prompt_hash}\n"
            "The held-out set is a MEASUREMENT INSTRUMENT, not a tuning "
            "input. Re-running it after a prompt change is only meaningful "
            "if the change was validated against the DEV set first.\n"
            "If you have done that, re-run with --acknowledge-retune. Your "
            "acknowledgement is recorded in docs/results/heldout_runs.jsonl.",
            code=2,
        )

    print(f"release_eval: git={_git_commit()[:12]}  model={model}  "
          f"prompt_sha256={prompt_hash[:12]}", flush=True)

    dev_summary = _run_set(_load_cases(dev_path), model, "dev")
    heldout_summary = _run_set(_load_cases(heldout_path), model, "heldout")

    summary = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": _git_commit(),
        "model": model,
        "prompt_hash": prompt_hash,
        "prompt_source": prompt_source,
        "acknowledged_retune": bool(args.acknowledge_retune),
        "dev": dev_summary,
        "heldout": heldout_summary,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / "C-release-eval.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_md(summary, RESULTS_DIR / "C-release-eval.md")
    _append_ledger({
        "at": summary["at"],
        "git_commit": summary["git_commit"],
        "model": model,
        "prompt_hash": prompt_hash,
        "prompt_source": prompt_source,
        "acknowledged_retune": summary["acknowledged_retune"],
        "heldout_pass_rate": heldout_summary["pass_rate"],
        "heldout_wrong_cuts": heldout_summary["wrong_cuts"],
        "heldout_p50_ms": heldout_summary["p50_ms"],
        "heldout_p95_ms": heldout_summary["p95_ms"],
        "dev_pass_rate": dev_summary["pass_rate"],
    })

    print("\n=== SUMMARY ===")
    print(json.dumps({
        "model": model, "git_commit": summary["git_commit"],
        "prompt_hash": prompt_hash,
        "dev": {k: dev_summary[k] for k in
                ("cases", "pass_rate", "wrong_cuts", "p50_ms", "p95_ms")},
        "heldout": {k: heldout_summary[k] for k in
                    ("cases", "pass_rate", "wrong_cuts", "p50_ms", "p95_ms")},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
