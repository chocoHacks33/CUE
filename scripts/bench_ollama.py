"""Sequential-parse benchmark for the Ollama fast/full modes.

Prints first-call and steady-state (call 2..N) latency stats plus mean
tokens generated per call. Dev-only; not part of the release path.

Usage:
  python scripts/bench_ollama.py --model llama3.2:3b --mode fast --n 10
  python scripts/bench_ollama.py --model llama3.2:3b --mode full --n 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ollama_parser import parse_via_ollama  # noqa: E402


def load_dev_utterances(n: int) -> list[str]:
    path = Path(__file__).resolve().parent / "data" / "adversarial.json"
    data = json.loads(path.read_text())
    cases = data["cases"] if isinstance(data, dict) else data
    # Spread across categories; stable order.
    picked, seen = [], set()
    for c in cases:
        cat = c.get("cat")
        if cat not in seen:
            picked.append(c["say"])
            seen.add(cat)
        if len(picked) >= n:
            break
    # Fill up to n from the head if we ran out of categories.
    idx = 0
    while len(picked) < n and idx < len(cases):
        s = cases[idx]["say"]
        if s not in picked:
            picked.append(s)
        idx += 1
    return picked[:n]


def summarise(name: str, latencies_ms: list[float], tokens: list[int]) -> None:
    if not latencies_ms:
        print(f"{name}: no data")
        return
    xs = sorted(latencies_ms)
    p50 = xs[len(xs) // 2]
    p95 = xs[int(0.95 * (len(xs) - 1))]
    mean_toks = statistics.mean(tokens) if tokens else 0
    print(f"  {name:14s} n={len(xs):2d}  "
          f"p50={p50:6.0f}ms  p95={p95:6.0f}ms  "
          f"min={xs[0]:6.0f}  max={xs[-1]:6.0f}  "
          f"mean_tokens={mean_toks:5.1f}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--mode", choices=("fast", "full"), default="fast")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args(argv)

    utterances = load_dev_utterances(args.n)
    print(f"# bench: model={args.model}  mode={args.mode}  n={len(utterances)}")

    lats: list[float] = []
    toks: list[int] = []
    for i, u in enumerate(utterances):
        cue, ms, ntoks = parse_via_ollama(u, args.model, fast=(args.mode == "fast"))
        lats.append(ms)
        toks.append(ntoks)
        print(f"  [{i+1:2d}] {ms:6.0f}ms  tokens={ntoks:3d}  action={cue.action.value:4s}  "
              f'target={cue.target_guest_ids}  say="{u}"')

    print()
    if lats:
        summarise("first-call", lats[:1], toks[:1])
        if len(lats) > 1:
            summarise("steady-state", lats[1:], toks[1:])
            summarise("all", lats, toks)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
