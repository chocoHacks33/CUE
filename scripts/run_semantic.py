"""Run one of the semantic evaluation sets against one or more models.

Usage (from apps/api's venv, after `pip install -e ".[dev]"` and the
one-line dep additions in the follow-up commit):

  python scripts/run_semantic.py --models MODEL_A MODEL_B \\
      [--set dev|heldout] [--only CATEGORY] [--repeat N]

Sets:
  dev      -> scripts/data/adversarial.json (development corpus; use for tuning)
  heldout  -> scripts/data/heldout.json     (release set; NEVER touch to tune the prompt)

Gate for M1: pass rate >= 90% on dev, zero wrong SHOW cuts, p95 latency recorded.
Release gate uses heldout with the pinned model + prompt.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# Support running from a checkout without `pip install -e`
REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cue_api.semantics.parser import ProgrammeContext, parse  # noqa: E402

SETS = {
    "dev": "adversarial.json",
    "heldout": "heldout.json",
}
DATA_DIR = Path(__file__).parent / "data"


def load_cases(set_name):
    path = DATA_DIR / SETS[set_name]
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        return data.get("cases", []), data.get("note", "")
    return data, ""


def check(case, cue):
    if cue.action.value not in case["action"]:
        return False
    if cue.action.value == "SHOW" and "target_guest_ids" in case:
        return sorted(cue.target_guest_ids) == sorted(case["target_guest_ids"])
    return True


def _programme_for(case):
    p = case.get("programme")
    if not p:
        return None
    return ProgrammeContext(**p)


def run(cases, set_name, model, only, repeat):
    rows, lat = [], []
    for case in cases:
        if only and case["cat"] != only:
            continue
        for _ in range(repeat):
            cue, ms = parse(
                case["say"], model=model,
                programme=_programme_for(case),
                roster=case.get("roster"),
                context=case.get("context") or "",
            )
            ok = check(case, cue)
            wrong_cut = (not ok) and cue.action.value == "SHOW"   # the worst failure
            lat.append(ms)
            rows.append({
                "id": case["id"], "cat": case["cat"], "say": case["say"],
                "expected": case["action"], "got": cue.model_dump(mode="json"),
                "ok": ok, "wrong_cut": wrong_cut, "ms": round(ms),
            })
            marker = "PASS" if ok else ("WRONG_CUT" if wrong_cut else "FAIL")
            print(f'{marker:>9} {case["id"]:14} {ms:5.0f}ms  '
                  f'{cue.action.value:4} {cue.target_guest_ids}  "{case["say"]}"')
    lat.sort()
    passed = sum(r["ok"] for r in rows)
    wrong_cuts = sum(r["wrong_cut"] for r in rows)
    other_fails = len(rows) - passed - wrong_cuts
    summary = {
        "set": set_name, "model": model, "cases": len(rows), "passed": passed,
        "pass_rate": round(passed / len(rows), 3) if rows else 0.0,
        # WRONG SHOW cuts are the worst failure and get their own line.
        "wrong_cuts": wrong_cuts,
        "other_fails": other_fails,
        "p50_ms": round(statistics.median(lat)) if lat else 0,
        "p95_ms": round(lat[int(0.95 * (len(lat) - 1))]) if lat else 0,
    }
    out = (Path(__file__).parent
           / f"results_{set_name}_{model.replace('/', '_')}_{int(time.time())}.json")
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--set", dest="set_name", choices=list(SETS), default="dev",
                    help="which evaluation set to run (default: dev)")
    ap.add_argument("--only", help="run one category, e.g. FUTURE")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()

    cases, note = load_cases(a.set_name)
    print(f"# set: {a.set_name}  ({len(cases)} cases from data/{SETS[a.set_name]})")
    if note:
        print(f"# note: {note}")

    summaries = [run(cases, a.set_name, m, a.only, a.repeat) for m in a.models]
    print("\n=== SUMMARY ===")
    for s in summaries:
        print(json.dumps(s))
