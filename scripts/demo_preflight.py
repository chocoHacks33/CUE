"""One-command preflight before every demo. Prints GO or NO-GO per check
and an overall verdict. Exit 0 only if every check is GO.

Checks
------
1. OPENAI_API_KEY present            (never printed)
2. DEEPGRAM_API_KEY present          (never printed)
3. CUE_MODEL pinned                  (env var, no default)
4. Roster loads                      (semantics/roster.json parses)
5. OpenAI reachable                  (skipped with --offline)
6. Deepgram reachable                (skipped with --offline)
7. Default microphone found          (sounddevice enumeration)
8. Microphone level > 0              (short capture)
9. Fixture timeline runs clean       (import + run one utterance)

Usage
-----
    python scripts/demo_preflight.py            # full preflight
    python scripts/demo_preflight.py --offline  # skip network checks
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class Check:
    """One preflight check result. Never carries a secret in `detail`."""
    __slots__ = ("name", "ok", "detail", "skipped")

    def __init__(self, name: str, ok: bool, detail: str = "", skipped: bool = False):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.skipped = skipped

    def line(self) -> str:
        mark = "SKIP" if self.skipped else ("GO  " if self.ok else "NO-GO")
        detail = f"  ({self.detail})" if self.detail else ""
        return f"[{mark}] {self.name}{detail}"


def _secret_present(name: str) -> Check:
    v = os.environ.get(name, "")
    if not v:
        return Check(f"{name} present", False, "missing from env")
    return Check(f"{name} present", True, f"len={len(v)}")  # length only


def _cue_model_pinned() -> Check:
    v = os.environ.get("CUE_MODEL", "")
    if not v:
        return Check("CUE_MODEL pinned", False, "missing from env")
    return Check("CUE_MODEL pinned", True, v)


def _roster_loads() -> Check:
    path = _SRC / "cue_api" / "semantics" / "roster.json"
    if not path.exists():
        return Check("Roster loads", False, "roster.json missing")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return Check("Roster loads", False, f"json error: {e.msg}")
    guests = data.get("guests") or []
    if not guests:
        return Check("Roster loads", False, "no guests")
    for g in guests:
        if not g.get("id") or not g.get("name"):
            return Check("Roster loads", False,
                         f"guest missing id/name: {g!r}")
    return Check("Roster loads", True, f"{len(guests)} guests")


def _openai_reachable() -> Check:
    try:
        from openai import OpenAI
        client = OpenAI()
        # Cheapest possible reachability call: list a small page of models.
        models = client.models.list()
        first = next(iter(getattr(models, "data", []) or []), None)
        if first is None:
            return Check("OpenAI reachable", False, "empty models list")
        return Check("OpenAI reachable", True, "models.list OK")
    except Exception as e:  # noqa: BLE001
        return Check("OpenAI reachable", False,
                     f"{type(e).__name__}: {str(e)[:80]}")


def _deepgram_reachable() -> Check:
    try:
        from deepgram import DeepgramClient
        client = DeepgramClient()
        # Reachability via the projects listing (small, doesn't consume
        # streaming credits). If the account has no projects the call
        # still returns 200 with an empty list.
        try:
            client.manage.v1.list_projects()  # type: ignore[attr-defined]
        except AttributeError:
            # Different SDK layout — fall back to a socket dial.
            import socket
            with socket.create_connection(("api.deepgram.com", 443),
                                          timeout=3.0):
                pass
        return Check("Deepgram reachable", True, "api.deepgram.com OK")
    except Exception as e:  # noqa: BLE001
        return Check("Deepgram reachable", False,
                     f"{type(e).__name__}: {str(e)[:80]}")


def _mic_found_and_level() -> tuple[Check, Check]:
    try:
        import sounddevice as sd
    except Exception as e:  # noqa: BLE001
        c = Check("Default microphone found", False,
                  f"sounddevice: {type(e).__name__}")
        return c, Check("Microphone level > 0", False, "no sounddevice")
    try:
        devs = sd.query_devices()
    except Exception as e:  # noqa: BLE001
        c = Check("Default microphone found", False,
                  f"query_devices: {type(e).__name__}")
        return c, Check("Microphone level > 0", False, "no devices")

    default_in = getattr(sd.default, "device", (None, None))[0]
    if default_in is None or default_in < 0 or default_in >= len(devs):
        found = None
        for i, d in enumerate(devs):
            if (d or {}).get("max_input_channels", 0) > 0:
                found = i; break
        if found is None:
            c = Check("Default microphone found", False, "no input device")
            return c, Check("Microphone level > 0", False, "no input device")
        default_in = found
    dev = devs[default_in]
    found_c = Check("Default microphone found", True,
                    f"[{default_in}] {dev.get('name', '?')}")

    # ~250 ms capture via RawInputStream (numpy-free). If the device
    # is muted, rms comes out 0 - still a real signal (mic exists
    # but silent).
    try:
        import queue as _queue
        import struct
        q: _queue.Queue = _queue.Queue()

        def cb(indata, _frames, _t, _s):
            q.put(bytes(indata))

        stream = sd.RawInputStream(
            samplerate=16000, blocksize=1600, dtype="int16",
            channels=1, callback=cb, device=default_in,
        )
        buf = bytearray()
        with stream:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 0.35:
                try:
                    buf += q.get(timeout=0.3)
                except _queue.Empty:
                    break
                if len(buf) >= 32000:  # ~1 s of audio
                    break
        count = len(buf) // 2
        samples = struct.unpack(f"<{count}h", bytes(buf)) if count else ()
        sq = sum(int(s) * int(s) for s in samples)
        rms = (sq / count) ** 0.5 if count else 0.0
        pct = min(1.0, rms / 6000.0) * 100
        level_c = Check("Microphone level > 0", rms > 0,
                        f"rms={int(rms)} ({pct:.0f}%)")
    except Exception as e:  # noqa: BLE001
        level_c = Check("Microphone level > 0", False,
                        f"{type(e).__name__}: {str(e)[:60]}")
    return found_c, level_c


def _fixture_runs_clean() -> Check:
    """Import fixture_cues and run a single scripted utterance through
    DirectorSession without any network. Only checks it doesn't crash."""
    try:
        import io
        import contextlib as _ctx
        from cue_api.policy.session import DirectorSession
        from cue_api.semantics.parser import (
            Action, Cue, Intent, Scope, TemporalIntent,
        )
        session = DirectorSession(current_camera="CAM-HOST")
        cams = {
            "CAM-HOST":  {"role": "host",  "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                          "guest_ready": True},
            "CAM-GUEST": {"role": "guest", "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": ["sarah"],
                          "evidence_age_s": 0.4, "guest_ready": True},
            "CAM-WIDE":  {"role": "wide",  "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                          "guest_ready": True},
        }
        cue = Cue(
            target_guest_ids=["sarah"], scope=Scope.SINGLE,
            intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW, evidence_text="Please welcome Sarah Tan.",
        )
        with _ctx.redirect_stdout(io.StringIO()):
            d = session.on_cue(cue, cams, now=time.monotonic(),
                               role_based=True,
                               role_map={"sarah": "CAM-GUEST"})
        if d.action.value != "TAKE" or d.camera_id != "CAM-GUEST":
            return Check("Fixture timeline runs clean", False,
                         f"unexpected: {d.action.value} {d.camera_id}")
        return Check("Fixture timeline runs clean", True,
                     "single utterance -> TAKE CAM-GUEST")
    except Exception as e:  # noqa: BLE001
        return Check("Fixture timeline runs clean", False,
                     f"{type(e).__name__}: {str(e)[:80]}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="CUE demo preflight.")
    ap.add_argument("--offline", action="store_true",
                    help="Skip OpenAI + Deepgram reachability probes.")
    args = ap.parse_args(argv)

    checks: list[Check] = []
    checks.append(_secret_present("OPENAI_API_KEY"))
    checks.append(_secret_present("DEEPGRAM_API_KEY"))
    checks.append(_cue_model_pinned())
    checks.append(_roster_loads())
    if args.offline:
        checks.append(Check("OpenAI reachable", True,
                            "skipped (--offline)", skipped=True))
        checks.append(Check("Deepgram reachable", True,
                            "skipped (--offline)", skipped=True))
    else:
        checks.append(_openai_reachable())
        checks.append(_deepgram_reachable())
    mic_found, mic_level = _mic_found_and_level()
    checks.append(mic_found)
    checks.append(mic_level)
    checks.append(_fixture_runs_clean())

    for c in checks:
        print(c.line(), flush=True)
    non_skipped = [c for c in checks if not c.skipped]
    ok = all(c.ok for c in non_skipped)
    print("---")
    print("VERDICT: " + ("GO - every check passed."
                         if ok else "NO-GO - see the NO-GO lines above."))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
