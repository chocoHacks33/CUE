"""Run the adversarial set against one or more models.
Usage: python tests/semantics/run_semantic.py --models MODEL_A MODEL_B [--only FUTURE] [--repeat 1]
Gate for M1: pass rate >= 90%, zero wrong SHOW cuts, p95 latency recorded.
"""
import argparse, json, statistics, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "worker"))
from semantics.parser import parse  # noqa: E402

CASES = json.loads((Path(__file__).parent / "adversarial.json").read_text())

def check(case, cue):
    if cue.action.value not in case["action"]:
        return False
    if cue.action.value == "SHOW" and "target_guest_ids" in case:
        return sorted(cue.target_guest_ids) == sorted(case["target_guest_ids"])
    return True

def run(model, only, repeat):
    rows, lat = [], []
    for case in CASES:
        if only and case["cat"] != only:
            continue
        for _ in range(repeat):
            cue, ms = parse(case["say"], model=model)
            ok = check(case, cue)
            wrong_cut = (not ok) and cue.action.value == "SHOW"   # the worst failure
            lat.append(ms)
            rows.append({"id": case["id"], "cat": case["cat"], "say": case["say"],
                         "expected": case["action"], "got": cue.model_dump(mode="json"),
                         "ok": ok, "wrong_cut": wrong_cut, "ms": round(ms)})
            print(f'{"PASS" if ok else "FAIL"} {case["id"]:8} {ms:5.0f}ms  '
                  f'{cue.action.value:4} {cue.target_guest_ids}  "{case["say"]}"')
    lat.sort()
    passed = sum(r["ok"] for r in rows)
    summary = {"model": model, "cases": len(rows), "passed": passed,
               "pass_rate": round(passed / len(rows), 3),
               "wrong_cuts": sum(r["wrong_cut"] for r in rows),
               "p50_ms": round(statistics.median(lat)),
               "p95_ms": round(lat[int(0.95 * (len(lat) - 1))])}
    out = Path(__file__).parent / f"results_{model.replace('/', '_')}_{int(time.time())}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return summary

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--only", help="run one category, e.g. FUTURE")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    summaries = [run(m, a.only, a.repeat) for m in a.models]
    print("\n=== SUMMARY ===")
    for s in summaries:
        print(json.dumps(s))
