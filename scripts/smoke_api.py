"""Smoke-test that OPENAI_API_KEY and DEEPGRAM_API_KEY are set and functional.

Behaviour:
- Loads .env if present (via python-dotenv).
- Confirms each key exists in the environment. NEVER prints a key or its length.
- Makes the cheapest possible authenticated call to each provider and prints
  latency in milliseconds.
- Exits non-zero if any check fails; each failure prints a clear reason.

Usage:
  python scripts/smoke_api.py

Notes:
- OpenAI is the only supported semantic interpreter (CUE_PROVIDER=openai).
  Do not add Ollama or other-provider branches here.
- Deepgram check hits /v1/projects (auth-only, no audio, no cost).
"""
from __future__ import annotations

import os
import sys
import time
import json
import urllib.request
import urllib.error

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # tolerated: user may have exported env vars directly


DEEPGRAM_PROJECTS_URL = "https://api.deepgram.com/v1/projects"


def _ok(name, ms):
    print(f"  [OK]   {name:10s} {ms:6.0f} ms")


def _fail(name, msg):
    print(f"  [FAIL] {name:10s} {msg}")


def check_openai() -> bool:
    key = os.environ.get("OPENAI_API_KEY")
    provider = os.environ.get("CUE_PROVIDER", "openai").strip().lower()
    if provider != "openai":
        _fail("openai", f"CUE_PROVIDER={provider!r}; team decision is 'openai' only")
        return False
    if not key:
        _fail("openai", "OPENAI_API_KEY not set (expected in .env or environment)")
        return False
    try:
        from openai import OpenAI
    except ImportError as e:
        _fail("openai", f"openai SDK not importable: {e}")
        return False

    client = OpenAI()  # reads key from env
    t0 = time.perf_counter()
    try:
        # Cheapest authenticated call; no generation, no billing surprise.
        list(client.models.list())
    except Exception as e:
        # Deliberately do not include repr(e) at unlimited length in case an
        # error surface echoes back credentials.
        _fail("openai", f"{type(e).__name__} calling models.list()")
        return False
    ms = (time.perf_counter() - t0) * 1000
    _ok("openai", ms)
    return True


def check_deepgram() -> bool:
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        _fail("deepgram", "DEEPGRAM_API_KEY not set (expected in .env or environment)")
        return False
    req = urllib.request.Request(
        DEEPGRAM_PROJECTS_URL,
        headers={"Authorization": f"Token {key}", "Accept": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # Drain a small body to include full round-trip in the timing.
            resp.read(64)
    except urllib.error.HTTPError as e:
        _fail("deepgram", f"HTTP {e.code} from /v1/projects")
        return False
    except Exception as e:
        _fail("deepgram", f"{type(e).__name__} contacting Deepgram")
        return False
    ms = (time.perf_counter() - t0) * 1000
    _ok("deepgram", ms)
    return True


def main() -> int:
    print("smoke_api: verifying live credentials (keys are never printed)")
    results = [check_openai(), check_deepgram()]
    if all(results):
        print("all providers reachable.")
        return 0
    print("one or more providers failed; see [FAIL] lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
