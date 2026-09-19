"""Read scripted sentences aloud, measure Deepgram accuracy with/without keyterms.

Interactive: prints one sentence at a time, waits for you to press ENTER, then
records ~6 seconds of audio while you read it aloud. Every sentence is sent
to Deepgram twice: once with the roster's names+aliases as keyterms, once
without. Word Error Rate is computed against the exact scripted text, plus a
separate metric that only counts errors on guest-name tokens.

Results are appended to docs/results/C-caption-accuracy.md.

Usage (from repo root, apps/api's venv active):
  python scripts/caption_accuracy.py                 # 10 default sentences
  python scripts/caption_accuracy.py --n 5           # first N only
  python scripts/caption_accuracy.py --record-secs 8 # longer capture per line
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

RESULTS_MD = REPO_ROOT / "docs" / "results" / "C-caption-accuracy.md"

# 10 scripted sentences drawn from the demo. Every one contains at least one
# guest name so we can measure name-only WER separately.
SCRIPT: list[str] = [
    "Please welcome Sarah Tan.",
    "Sarah, please come up.",
    "Actually Sarah, please join us now.",
    "Sarah joins us after the break.",
    "Please welcome our founder, Alex Rivera.",
    "Over to you, Daniel.",
    "Big hand for Maya Chen, everybody.",
    "Jordan, why don't you kick us off.",
    "Kai Nakamura, welcome to the stage.",
    "Please welcome Sarah, actually Daniel.",
]


def _roster_keyterms() -> list[str]:
    roster_path = _SRC / "cue_api" / "semantics" / "roster.json"
    if not roster_path.exists():
        return []
    data = json.loads(roster_path.read_text())
    terms: set[str] = set()
    for g in data.get("guests", []):
        terms.add(g.get("name", ""))
        for a in g.get("aliases", []) or []:
            terms.add(a)
    return sorted(t for t in terms if t)


def _guest_first_names() -> set[str]:
    """Lowercased short/first names for the name-only WER metric."""
    roster_path = _SRC / "cue_api" / "semantics" / "roster.json"
    if not roster_path.exists():
        return set()
    data = json.loads(roster_path.read_text())
    out: set[str] = set()
    for g in data.get("guests", []):
        for a in g.get("aliases", []) or []:
            out.add(str(a).split()[0].lower())
        name = g.get("name", "")
        if name:
            out.add(name.split()[0].lower())
    return out


# ---------------------------------------------------------------- audio capture

def _record_pcm(seconds: float, sample_rate: int = 16000) -> bytes:
    import sounddevice as sd
    frames = int(seconds * sample_rate)
    data = sd.rec(frames, samplerate=sample_rate, channels=1,
                  dtype="int16", blocking=True)
    return bytes(data.tobytes())


# ---------------------------------------------------------------- deepgram REST

def _transcribe(pcm: bytes, sample_rate: int, keyterm: list[str] | None) -> tuple[str, float]:
    """One-shot pre-recorded transcription. Returns (transcript, wall-ms)."""
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY not set")
    params = {
        "model": "nova-3",
        "language": "en-US",
        "smart_format": "true",
        "encoding": "linear16",
        "sample_rate": str(sample_rate),
        "channels": "1",
    }
    qs = "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())
    if keyterm:
        qs += "&" + "&".join(
            f"keyterm={urllib.parse.quote(k)}" for k in keyterm
        )
    url = f"https://api.deepgram.com/v1/listen?{qs}"
    req = urllib.request.Request(url, data=pcm, method="POST",
                                 headers={
                                     "Authorization": f"Token {key}",
                                     "Content-Type": f"audio/l16;rate={sample_rate}",
                                 })
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.load(resp)
    ms = (time.perf_counter() - t0) * 1000
    try:
        alt = (
            result["results"]["channels"][0]["alternatives"][0]
        )
    except (KeyError, IndexError):
        return "", ms
    return alt.get("transcript", "") or "", ms


# ---------------------------------------------------------------- WER

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _wer(ref: list[str], hyp: list[str]) -> float:
    """Standard word error rate via Levenshtein on tokens."""
    if not ref:
        return 0.0 if not hyp else 1.0
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m] / n


def _name_only_wer(ref: list[str], hyp: list[str], name_set: set[str]) -> float | None:
    """WER counted only over reference tokens that are guest names."""
    ref_names = [w for w in ref if w in name_set]
    if not ref_names:
        return None
    hyp_names = [w for w in hyp if w in name_set]
    return _wer(ref_names, hyp_names)


# ---------------------------------------------------------------- driver

def _run_one(sentence: str, keyterms: list[str], seconds: float,
             names: set[str]) -> dict:
    print()
    print(f'> "{sentence}"')
    input("  press ENTER, then read the line aloud ... ")
    print(f"  recording {seconds:.0f} seconds ...")
    pcm = _record_pcm(seconds)

    hyp_kt,  ms_kt  = _transcribe(pcm, 16000, keyterm=keyterms)
    hyp_no,  ms_no  = _transcribe(pcm, 16000, keyterm=None)

    ref_tokens = _tokens(sentence)
    hyp_kt_toks = _tokens(hyp_kt)
    hyp_no_toks = _tokens(hyp_no)

    row = {
        "sentence": sentence,
        "heard_keyterm":    hyp_kt,
        "heard_no_keyterm": hyp_no,
        "wer_keyterm":      _wer(ref_tokens, hyp_kt_toks),
        "wer_no_keyterm":   _wer(ref_tokens, hyp_no_toks),
        "wer_names_keyterm":    _name_only_wer(ref_tokens, hyp_kt_toks, names),
        "wer_names_no_keyterm": _name_only_wer(ref_tokens, hyp_no_toks, names),
        "latency_ms_keyterm":    round(ms_kt),
        "latency_ms_no_keyterm": round(ms_no),
    }
    print(f'  heard (with keyterm):    "{hyp_kt}"  WER={row["wer_keyterm"]:.2f}')
    print(f'  heard (without keyterm): "{hyp_no}"  WER={row["wer_no_keyterm"]:.2f}')
    return row


def _summary_line(rows: list[dict], key: str) -> str:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return "n/a"
    return f"mean={statistics.mean(vals):.2f}  median={statistics.median(vals):.2f}  n={len(vals)}"


def _write_results(rows: list[dict]) -> None:
    RESULTS_MD.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_MD.open("a", encoding="utf-8") as f:
        f.write("\n\n# Deepgram caption accuracy — "
                + time.strftime("%Y-%m-%d %H:%M:%S")
                + "\n\n")
        f.write(
            "| # | sentence | heard (keyterm on) | WER-kt | WER-no-kt |"
            " names WER-kt | names WER-no-kt |\n"
        )
        f.write("|---:|---|---|---:|---:|---:|---:|\n")
        for i, r in enumerate(rows, 1):
            names_kt = _fmt_opt(r["wer_names_keyterm"])
            names_no = _fmt_opt(r["wer_names_no_keyterm"])
            f.write(f"| {i} | {r['sentence']} | {r['heard_keyterm']} | "
                    f"{r['wer_keyterm']:.2f} | {r['wer_no_keyterm']:.2f} | "
                    f"{names_kt} | {names_no} |\n")
        f.write("\n**overall WER (keyterm on):** "
                + _summary_line(rows, "wer_keyterm") + "\n\n")
        f.write("**overall WER (no keyterm):** "
                + _summary_line(rows, "wer_no_keyterm") + "\n\n")
        f.write("**guest-name WER (keyterm on):** "
                + _summary_line(rows, "wer_names_keyterm") + "\n\n")
        f.write("**guest-name WER (no keyterm):** "
                + _summary_line(rows, "wer_names_no_keyterm") + "\n\n")
        f.write("_Values are 0.00 = perfect, 1.00 = every reference token wrong._\n")


def _fmt_opt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=len(SCRIPT),
                    help=f"how many sentences (max {len(SCRIPT)})")
    ap.add_argument("--record-secs", type=float, default=6.0)
    args = ap.parse_args(argv)

    if not os.environ.get("DEEPGRAM_API_KEY"):
        print("DEEPGRAM_API_KEY is not set. Put it in .env and try again.",
              file=sys.stderr)
        return 2

    keyterms = _roster_keyterms()
    names = _guest_first_names()
    print(f"keyterms in use: {keyterms}")
    print(f"guest-name tokens tracked for the name-only WER: {sorted(names)}")

    picked = SCRIPT[: max(0, min(args.n, len(SCRIPT)))]
    rows: list[dict] = []
    for s in picked:
        rows.append(_run_one(s, keyterms, args.record_secs, names))

    _write_results(rows)
    print()
    print(f"appended results to {RESULTS_MD}")
    print("overall WER (keyterm on):     " + _summary_line(rows, "wer_keyterm"))
    print("overall WER (no keyterm):     " + _summary_line(rows, "wer_no_keyterm"))
    print("guest-name WER (keyterm on):  " + _summary_line(rows, "wer_names_keyterm"))
    print("guest-name WER (no keyterm):  " + _summary_line(rows, "wer_names_no_keyterm"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
