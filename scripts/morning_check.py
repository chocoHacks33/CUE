"""One-command Sunday morning re-establish check for the C-lane.

Walks the operator through six sub-steps, each printing GO or NO-GO,
and writes ``docs/results/C-stage7-morning.md``. Secrets are loaded
from ``../CUE/.env`` (the desk worktree, git-ignored). No key value is
ever printed, logged or written to disk by this script.

Sub-steps
---------
(a) demo_preflight.py with network checks
(b) Room noise: 5 s silence + 5 s speech, report both levels and the
    signal-to-noise gap. NO-GO if the gap is under 10 dB.
(c) Speaker positions: read the same sentence from the host position,
    then from the guest position. Report Deepgram confidence and word
    error rate. NO-GO if guest position drops below 85 percent word
    accuracy.
(d) Five demo sentences through live Deepgram with keyterms on:
    transcript, guest-name accuracy, first-word and end-of-turn latency.
(e) If OPENAI_API_KEY and CUE_MODEL are present: run the same five
    sentences through the full live lane and record cue, decision and
    per-hop latency. Else NOT RUN with the exact teammate command.
(f) Fixture timeline + 2 minute soak.

Usage
-----
    python scripts/morning_check.py
    python scripts/morning_check.py --skip-audio   # for CI regression only
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue as _queue
import re
import subprocess
import sys
import time
import traceback
import wave
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# --- .env loading: from ../CUE/.env, then repo root, in that order ---
DESK_ENV = REPO_ROOT.parent / "CUE" / ".env"
try:
    from dotenv import load_dotenv
    if DESK_ENV.exists():
        load_dotenv(DESK_ENV)
    load_dotenv()  # any repo-local .env
except Exception:  # noqa: BLE001 -- best-effort
    pass


SAMPLE_RATE = 16000
CLIP_BYTES_PER_SEC = SAMPLE_RATE * 2  # int16 mono

# Five demo sentences from the runbook.
DEMO_SENTENCES: list[str] = [
    "Please welcome Sarah Tan.",
    "Priya, could you jump in?",
    "Actually Sarah, sorry, Daniel.",
    "Please welcome Sarah and Daniel.",
    "Thanks both. Back to me.",
]

# Guest first names for keyterm biasing and WER of guest names.
GUEST_KEYTERMS: list[str] = [
    "Sarah", "Daniel", "Priya", "Maya", "Alex", "Jordan", "Kai",
    "Sarah Tan", "Daniel Reyes", "Priya Shah",
]

SNR_MIN_DB = 10.0
GUEST_ACC_MIN = 0.85


@dataclass
class StepResult:
    name: str
    verdict: str  # "GO", "NO-GO", "SKIP", "NOT RUN"
    lines: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def is_blocker(self) -> bool:
        return self.verdict == "NO-GO"


# ---------------------------------------------------------------- utils

def _dbfs(rms: float) -> float:
    if rms <= 0.0:
        return -120.0
    return 20.0 * math.log10(rms / 32768.0)


def _rms_int16(samples: bytes) -> float:
    if not samples:
        return 0.0
    import struct
    n = len(samples) // 2
    if n == 0:
        return 0.0
    ints = struct.unpack(f"<{n}h", samples[: n * 2])
    sq = sum(int(s) * int(s) for s in ints)
    return math.sqrt(sq / n)


def _record_seconds(sd, seconds: float, device: int | None,
                    countdown: bool = True) -> bytes:
    """Capture `seconds` of int16 mono @16k, return raw PCM bytes."""
    q: _queue.Queue = _queue.Queue()

    def cb(indata, _f, _t, _s):
        q.put(bytes(indata))

    if countdown:
        for i in range(3, 0, -1):
            print(f"    starting in {i}...", flush=True)
            time.sleep(1.0)
    print(f"    recording {seconds:.1f}s", flush=True)
    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE, blocksize=1600, dtype="int16",
        channels=1, callback=cb, device=device,
    )
    buf = bytearray()
    with stream:
        t0 = time.monotonic()
        target_bytes = int(seconds * CLIP_BYTES_PER_SEC)
        while len(buf) < target_bytes:
            try:
                buf += q.get(timeout=1.0)
            except _queue.Empty:
                if time.monotonic() - t0 > seconds + 2.0:
                    break
    print(f"    captured {len(buf)} bytes ({len(buf) / CLIP_BYTES_PER_SEC:.1f}s)",
          flush=True)
    return bytes(buf[: int(seconds * CLIP_BYTES_PER_SEC)])


def _write_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


_WORD_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _wer(reference: str, hypothesis: str) -> float:
    """Word error rate via Levenshtein. Returns 0.0..1.0+ (can exceed 1)."""
    ref = _tokens(reference)
    hyp = _tokens(hypothesis)
    if not ref:
        return 1.0 if hyp else 0.0
    # DP table
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1] / len(ref)


def _dg_batch_transcribe(pcm: bytes, keyterms: list[str] | None = None,
                         model: str = "nova-3") -> dict:
    """Send raw PCM (int16 mono 16k) to Deepgram v1 REST and return the
    parsed JSON. Requires DEEPGRAM_API_KEY. Times out at 20s."""
    import urllib.parse
    import urllib.request
    key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY not set")
    params = {
        "model": model, "language": "en", "smart_format": "true",
        "encoding": "linear16", "sample_rate": str(SAMPLE_RATE),
        "channels": "1", "punctuate": "true",
    }
    qs = urllib.parse.urlencode(params)
    if keyterms:
        # Deepgram takes multi-value keyterm params via repeated keys.
        qs += "&" + "&".join(
            f"keyterm={urllib.parse.quote(k)}" for k in keyterms
        )
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?{qs}",
        data=pcm,
        headers={
            "Authorization": f"Token {key}",
            "Content-Type": "audio/wav",  # v1 also accepts raw linear16
        },
        method="POST",
    )
    # We need a WAV wrapper for `Content-Type: audio/wav`. Wrap on the fly.
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    req.data = buf.getvalue()
    with urllib.request.urlopen(req, timeout=20.0) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------- (a) preflight

def step_a_preflight(python: str) -> StepResult:
    r = StepResult(name="(a) demo_preflight (network on)", verdict="NO-GO")
    cmd = [python, str(REPO_ROOT / "scripts" / "demo_preflight.py")]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=60.0)
    except Exception as e:  # noqa: BLE001
        r.lines.append(f"exec error: {type(e).__name__}: {e}")
        return r
    tail = (proc.stdout or "").strip().splitlines()[-15:]
    r.lines.extend(tail)
    r.data["exit"] = proc.returncode
    r.verdict = "GO" if proc.returncode == 0 else "NO-GO"
    return r


# ---------------------------------------------------------------- (b) SNR

def step_b_snr(sd, device: int | None) -> StepResult:
    r = StepResult(name="(b) Room noise SNR", verdict="NO-GO")
    print("  hold still, do NOT speak. Silence sample coming up.", flush=True)
    silence = _record_seconds(sd, 5.0, device)
    print("  now SPEAK naturally for 5 seconds (any words).", flush=True)
    speech = _record_seconds(sd, 5.0, device)
    rms_s = _rms_int16(silence)
    rms_v = _rms_int16(speech)
    db_s = _dbfs(rms_s)
    db_v = _dbfs(rms_v)
    gap = db_v - db_s
    r.data.update({
        "silence_rms": round(rms_s, 1), "silence_dbfs": round(db_s, 1),
        "speech_rms": round(rms_v, 1), "speech_dbfs": round(db_v, 1),
        "snr_db": round(gap, 1),
    })
    r.lines += [
        f"silence: rms={rms_s:.1f}  dBFS={db_s:.1f}",
        f"speech:  rms={rms_v:.1f}  dBFS={db_v:.1f}",
        f"gap:     {gap:.1f} dB   (min {SNR_MIN_DB} dB)",
    ]
    r.verdict = "GO" if gap >= SNR_MIN_DB else "NO-GO"
    if r.verdict == "NO-GO":
        r.lines.append("Advice: move the mic closer or reduce room noise.")
    return r


# ---------------------------------------------------------------- (c) positions

_POS_SENTENCE = ("Please welcome Sarah Tan and Daniel Reyes to the stage.")


def _pos_metrics(pcm: bytes, ref: str) -> dict:
    payload = _dg_batch_transcribe(pcm, keyterms=GUEST_KEYTERMS)
    chan = (payload.get("results", {}) or {}).get("channels", [])
    if not chan:
        return {"transcript": "", "confidence": None, "wer": None,
                "accuracy": None}
    alt = (chan[0].get("alternatives") or [{}])[0]
    transcript = alt.get("transcript", "") or ""
    conf = alt.get("confidence")
    w = _wer(ref, transcript)
    return {"transcript": transcript,
            "confidence": round(conf, 3) if isinstance(conf, (int, float)) else None,
            "wer": round(w, 3),
            "accuracy": round(1.0 - w, 3)}


def step_c_positions(sd, device: int | None) -> StepResult:
    r = StepResult(name="(c) Speaker positions", verdict="NO-GO")
    if not os.environ.get("DEEPGRAM_API_KEY"):
        r.verdict = "NOT RUN"
        r.lines.append("DEEPGRAM_API_KEY missing; cannot batch-transcribe.")
        return r
    print("  read this sentence from the HOST position:", flush=True)
    print(f'    "{_POS_SENTENCE}"', flush=True)
    host_pcm = _record_seconds(sd, 6.0, device)
    print("  now read the SAME sentence from the GUEST position:", flush=True)
    print(f'    "{_POS_SENTENCE}"', flush=True)
    guest_pcm = _record_seconds(sd, 6.0, device)
    try:
        host = _pos_metrics(host_pcm, _POS_SENTENCE)
        guest = _pos_metrics(guest_pcm, _POS_SENTENCE)
    except Exception as e:  # noqa: BLE001
        r.verdict = "NO-GO"
        r.lines.append(f"deepgram error: {type(e).__name__}: {str(e)[:120]}")
        return r
    r.data.update({"host": host, "guest": guest})
    for label, m in (("host", host), ("guest", guest)):
        r.lines.append(
            f"{label}:  transcript={m['transcript']!r}  "
            f"confidence={m['confidence']}  "
            f"WER={m['wer']}  accuracy={m['accuracy']}"
        )
    guest_acc = guest["accuracy"] or 0.0
    if guest_acc >= GUEST_ACC_MIN:
        r.verdict = "GO"
    else:
        r.verdict = "NO-GO"
        r.lines.append(
            f"Advice: guest word accuracy {guest_acc:.2f} < "
            f"{GUEST_ACC_MIN:.2f}. Move the mic or hand the speaker a lav.",
        )
    return r


# ---------------------------------------------------------------- (d) 5 sentences

def _dg_stream_five(sd, device: int | None) -> list[dict]:
    """Open one Deepgram v1 streaming session and drive five sentences.

    Returns per-sentence dicts with keys:
      prompt, transcript, first_word_ms, eot_ms, keyterm_hits, matched.
    """
    from deepgram import DeepgramClient
    from deepgram.core.events import EventType

    client = DeepgramClient()
    kwargs = {
        "model": "nova-3", "language": "en-US", "encoding": "linear16",
        "sample_rate": str(SAMPLE_RATE), "channels": "1",
        "smart_format": "true", "interim_results": "true",
        "endpointing": "300", "utterance_end_ms": "1000",
        "vad_events": "true",
    }

    results: list[dict] = []
    cur: dict = {}
    finalised = False

    def on_message(message, **_):
        nonlocal finalised
        payload = message.model_dump()
        t = payload.get("type", "")
        if t == "Results":
            alt = ((payload.get("channel") or {}).get("alternatives") or [{}])[0]
            words = alt.get("words") or []
            is_final = bool(payload.get("is_final"))
            if words and cur.get("first_word_ms") is None:
                # Time of first word arrival relative to sentence start.
                cur["first_word_ms"] = (time.monotonic() - cur["t0"]) * 1000
            if is_final and words:
                cur.setdefault("transcript_parts", []).append(alt.get("transcript", ""))
                cur["last_word_end"] = words[-1].get("end", cur.get("last_word_end"))
        elif t == "UtteranceEnd":
            cur["eot_ms"] = (time.monotonic() - cur["t0"]) * 1000
            finalised = True

    cm = client.listen.v1.connect(**kwargs)
    with cm as conn:
        conn.on(EventType.MESSAGE, on_message)
        # start listening in a background thread
        import threading
        listen_thread = threading.Thread(target=conn.start_listening, daemon=True)
        listen_thread.start()
        time.sleep(0.6)  # let socket open

        q: _queue.Queue = _queue.Queue(maxsize=256)

        def cb(indata, _f, _t, _s):
            try:
                q.put_nowait(bytes(indata))
            except _queue.Full:
                pass

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=1600, dtype="int16",
            channels=1, callback=cb, device=device,
        )
        with stream:
            for i, sentence in enumerate(DEMO_SENTENCES, 1):
                cur.clear()
                cur.update({
                    "prompt": sentence, "t0": time.monotonic(),
                    "first_word_ms": None, "eot_ms": None,
                    "transcript_parts": [],
                })
                finalised = False
                print(f"\n>>> [{i}/{len(DEMO_SENTENCES)}] read this aloud:",
                      flush=True)
                print(f'    "{sentence}"', flush=True)
                # Baseline for the speaker to start speaking.
                deadline = time.monotonic() + 7.0
                while time.monotonic() < deadline and not finalised:
                    try:
                        chunk = q.get(timeout=0.1)
                    except _queue.Empty:
                        continue
                    try:
                        conn.send_media(chunk)
                    except Exception:  # noqa: BLE001
                        pass
                # Drain a moment for UtteranceEnd to arrive.
                extra_end = time.monotonic() + 1.8
                while time.monotonic() < extra_end and not finalised:
                    try:
                        chunk = q.get(timeout=0.1)
                    except _queue.Empty:
                        continue
                    try:
                        conn.send_media(chunk)
                    except Exception:  # noqa: BLE001
                        pass
                transcript = " ".join(cur.get("transcript_parts", [])).strip()
                hits = sum(
                    1 for k in GUEST_KEYTERMS
                    if k.lower() in transcript.lower()
                )
                expected_names = [
                    n for n in GUEST_KEYTERMS
                    if n.lower() in sentence.lower()
                ]
                matched = all(
                    n.lower() in transcript.lower() for n in expected_names
                )
                results.append({
                    "prompt": sentence,
                    "transcript": transcript,
                    "first_word_ms": (round(cur["first_word_ms"], 1)
                                       if cur.get("first_word_ms") else None),
                    "eot_ms": (round(cur["eot_ms"], 1)
                               if cur.get("eot_ms") else None),
                    "expected_names": expected_names,
                    "matched": matched,
                    "keyterm_hits": hits,
                })
    return results


def step_d_five_sentences(sd, device: int | None) -> StepResult:
    r = StepResult(name="(d) Five demo sentences via live Deepgram",
                   verdict="NO-GO")
    if not os.environ.get("DEEPGRAM_API_KEY"):
        r.verdict = "NOT RUN"
        r.lines.append("DEEPGRAM_API_KEY missing.")
        return r
    try:
        rows = _dg_stream_five(sd, device)
    except Exception as e:  # noqa: BLE001
        r.verdict = "NO-GO"
        r.lines.append(f"streaming error: {type(e).__name__}: {str(e)[:160]}")
        return r
    matched_count = sum(1 for row in rows if row["matched"])
    first_ms = [row["first_word_ms"] for row in rows if row["first_word_ms"]]
    eot_ms = [row["eot_ms"] for row in rows if row["eot_ms"]]
    r.data["rows"] = rows
    r.data["matched"] = matched_count
    r.data["total"] = len(rows)
    r.data["first_word_ms_p50"] = (round(sorted(first_ms)[len(first_ms) // 2], 1)
                                    if first_ms else None)
    r.data["eot_ms_p50"] = (round(sorted(eot_ms)[len(eot_ms) // 2], 1)
                             if eot_ms else None)
    for row in rows:
        r.lines.append(
            f"'{row['prompt']}' -> '{row['transcript']}'  "
            f"first={row['first_word_ms']}  eot={row['eot_ms']}  "
            f"names_ok={row['matched']}"
        )
    # NO-GO if fewer than 4/5 sentences match all expected guest names,
    # or if fewer than 3 have a measured first-word latency.
    if matched_count >= 4 and len(first_ms) >= 3:
        r.verdict = "GO"
    else:
        r.verdict = "NO-GO"
        r.lines.append(
            f"Advice: only {matched_count}/{len(rows)} sentences carried the "
            "expected guest names. Check the mic and keyterm biasing."
        )
    return r


# ---------------------------------------------------------------- (e) live lane

def step_e_live_lane(python: str) -> StepResult:
    r = StepResult(name="(e) Full live lane on the five demo sentences",
                   verdict="NOT RUN")
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("CUE_MODEL")
            and os.environ.get("DEEPGRAM_API_KEY")):
        r.lines.append(
            "OPENAI_API_KEY or CUE_MODEL or DEEPGRAM_API_KEY missing on this "
            "host."
        )
        r.lines.append("Run on the demo Mac:")
        r.lines.append("  python scripts/latency_run.py")
        return r
    cmd = [python, str(REPO_ROOT / "scripts" / "latency_run.py")]
    r.lines.append(f"invoking: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=600.0, input="")
    except subprocess.TimeoutExpired:
        r.verdict = "NO-GO"
        r.lines.append("timeout after 600s.")
        return r
    except Exception as e:  # noqa: BLE001
        r.verdict = "NO-GO"
        r.lines.append(f"exec error: {type(e).__name__}: {e}")
        return r
    r.lines.extend((proc.stdout or "").strip().splitlines()[-20:])
    r.data["exit"] = proc.returncode
    latency_json = REPO_ROOT / "docs" / "results" / "C-latency.json"
    if latency_json.exists():
        try:
            r.data["latency"] = json.loads(latency_json.read_text())
        except Exception:  # noqa: BLE001
            pass
    r.verdict = "GO" if proc.returncode == 0 else "NO-GO"
    return r


# ---------------------------------------------------------------- (f) fixture + soak

def step_f_fixture_and_soak(python: str) -> StepResult:
    r = StepResult(name="(f) Fixture timeline + 2-min soak", verdict="NO-GO")
    fixture_cmd = [python, str(REPO_ROOT / "scripts" / "fixture_cues.py")]
    soak_cmd = [python, str(REPO_ROOT / "scripts" / "soak_c_lane.py"),
                "--minutes", "2"]
    for label, cmd, timeout in (
        ("fixture_cues", fixture_cmd, 60.0),
        ("soak_c_lane_2min", soak_cmd, 240.0),
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
        except Exception as e:  # noqa: BLE001
            r.lines.append(f"{label}: exec error: {type(e).__name__}: {e}")
            r.verdict = "NO-GO"
            return r
        tail = (proc.stdout or "").strip().splitlines()[-8:]
        r.lines.append(f"--- {label} exit={proc.returncode}")
        r.lines.extend(tail)
        r.data[label] = {"exit": proc.returncode}
        if proc.returncode != 0:
            r.verdict = "NO-GO"
            return r
    r.verdict = "GO"
    return r


# ---------------------------------------------------------------- report

def _decision_from_results(results: dict) -> str:
    """Read release_eval + latency and pick AUTO vs ASSIST."""
    heldout_path = REPO_ROOT / "docs" / "results" / "C-release-eval.json"
    latency_path = REPO_ROOT / "docs" / "results" / "C-latency.json"
    reasons = []
    wrong_cuts = None
    pass_rate = None
    total_p95 = None
    if heldout_path.exists():
        try:
            he = json.loads(heldout_path.read_text())
            hd = he.get("heldout") or he
            wrong_cuts = hd.get("wrong_cuts")
            pass_rate = hd.get("pass_rate")
        except Exception:  # noqa: BLE001
            reasons.append("release_eval JSON unreadable")
    else:
        reasons.append("release_eval not run")
    if latency_path.exists():
        try:
            la = json.loads(latency_path.read_text())
            total = (la.get("hops") or {}).get("total_ms") or {}
            total_p95 = total.get("p95")
        except Exception:  # noqa: BLE001
            reasons.append("latency JSON unreadable")
    else:
        reasons.append("latency not run")
    can_auto = (wrong_cuts == 0
                and isinstance(pass_rate, (int, float)) and pass_rate >= 0.90
                and isinstance(total_p95, (int, float)) and total_p95 <= 2500)
    if can_auto:
        return (
            f"**AUTO** — heldout.wrong_cuts=0, pass_rate={pass_rate:.2f}, "
            f"total_p95={total_p95} ms."
        )
    return (
        "**ASSIST + role-based.**\n\n"
        "Reasons: " + ("; ".join(reasons) if reasons else "gate not met") + ".\n\n"
        "Say this once, out loud, at the top of the demo:\n\n"
        "> \"CUE is doing camera direction from role mappings — it isn't\n"
        "> face-recognising anyone tonight. Every suggestion is confirmed\n"
        "> by me before it fires.\""
    )


def write_report(results: list[StepResult], decision: str,
                 out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# C-lane · Stage 7 morning re-establish",
        "",
        f"_Ran at {time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())} UTC._",
        "",
        "## Decision",
        "",
        decision,
        "",
        "## GO / NO-GO table",
        "",
        "| Step | Verdict |",
        "|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {r.verdict} |")
    lines.append("")
    for r in results:
        lines += [f"## {r.name}", ""]
        for ln in r.lines:
            lines.append(f"    {ln}" if not ln.startswith("|") else ln)
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="C-lane Sunday morning check.")
    ap.add_argument("--skip-audio", action="store_true",
                    help="Skip audio-dependent steps b, c, d. For regression.")
    ap.add_argument("--input-device", dest="input_device", default=None)
    args = ap.parse_args(argv)

    python = sys.executable
    print(f"morning_check: python={python}", flush=True)
    print(f"morning_check: repo={REPO_ROOT}", flush=True)
    print(f"morning_check: .env={DESK_ENV} present={DESK_ENV.exists()}",
          flush=True)

    results: list[StepResult] = []

    # (a)
    print("\n=== (a) demo_preflight (network on) ===", flush=True)
    a = step_a_preflight(python)
    for ln in a.lines:
        print(ln, flush=True)
    print(f"[{a.verdict}] {a.name}", flush=True)
    results.append(a)

    # audio-dependent steps
    if not args.skip_audio:
        try:
            import sounddevice as sd
            device = None
            if args.input_device is not None:
                try:
                    device = int(args.input_device)
                except ValueError:
                    device = args.input_device
        except Exception as e:  # noqa: BLE001
            print(f"sounddevice unavailable: {e}. Skipping b/c/d.", flush=True)
            sd = None
        if sd is not None:
            print("\n=== (b) Room noise SNR ===", flush=True)
            b = step_b_snr(sd, device)
            for ln in b.lines:
                print(ln, flush=True)
            print(f"[{b.verdict}] {b.name}", flush=True)
            results.append(b)

            print("\n=== (c) Speaker positions ===", flush=True)
            c = step_c_positions(sd, device)
            for ln in c.lines:
                print(ln, flush=True)
            print(f"[{c.verdict}] {c.name}", flush=True)
            results.append(c)

            print("\n=== (d) Five sentences via Deepgram ===", flush=True)
            d = step_d_five_sentences(sd, device)
            for ln in d.lines:
                print(ln, flush=True)
            print(f"[{d.verdict}] {d.name}", flush=True)
            results.append(d)
    else:
        for label in ("(b) Room noise SNR", "(c) Speaker positions",
                       "(d) Five demo sentences via live Deepgram"):
            skipped = StepResult(name=label, verdict="SKIP",
                                 lines=["--skip-audio"])
            print(f"[SKIP] {label}", flush=True)
            results.append(skipped)

    # (e)
    print("\n=== (e) Full live lane on the five sentences ===", flush=True)
    e = step_e_live_lane(python)
    for ln in e.lines:
        print(ln, flush=True)
    print(f"[{e.verdict}] {e.name}", flush=True)
    results.append(e)

    # (f)
    print("\n=== (f) Fixture + 2 min soak ===", flush=True)
    f = step_f_fixture_and_soak(python)
    for ln in f.lines:
        print(ln, flush=True)
    print(f"[{f.verdict}] {f.name}", flush=True)
    results.append(f)

    decision = _decision_from_results({r.name: r for r in results})
    out = REPO_ROOT / "docs" / "results" / "C-stage7-morning.md"
    write_report(results, decision, out)

    print("\n=== GO / NO-GO ===", flush=True)
    for r in results:
        print(f"  {r.verdict:8s}  {r.name}", flush=True)
    print(f"\nDecision:\n{decision}", flush=True)
    print(f"\nWrote {out}", flush=True)

    # Exit 0 unless a real blocker exists. NOT RUN and SKIP are not blockers.
    return 1 if any(r.is_blocker() for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr, flush=True)
        sys.exit(130)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
