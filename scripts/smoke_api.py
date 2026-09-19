"""Smoke-test the C-lane runtime credentials.

Behaviour:
- Loads .env if present (via python-dotenv).
- Branches the semantic-provider check on CUE_PROVIDER (default: openai).
- Confirms each required key/endpoint reachable. NEVER prints a key or its length.
- Prints latency in milliseconds for each check.
- Exits non-zero if any check fails; each failure prints a clear reason.

Provider policy (see docs/results/C-stage0.md):
- CUE_PROVIDER=openai   -> production; checks a cheap authenticated OpenAI call.
- CUE_PROVIDER=ollama   -> dev-only fallback; checks that a local Ollama
                            server is reachable (default http://localhost:11434,
                            override with OLLAMA_URL). Not part of the release
                            gate; used when the OpenAI key isn't on this box.

Deepgram is always checked (auth-only GET on /v1/projects, no audio, no cost).

Usage:
  python scripts/smoke_api.py
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # tolerated: user may have exported env vars directly


DEEPGRAM_PROJECTS_URL = "https://api.deepgram.com/v1/projects"
OLLAMA_DEFAULT_URL = "http://localhost:11434"


def _ok(name: str, ms: float) -> None:
    print(f"  [OK]   {name:10s} {ms:6.0f} ms")


def _fail(name: str, msg: str) -> None:
    print(f"  [FAIL] {name:10s} {msg}")


def check_openai() -> bool:
    key = os.environ.get("OPENAI_API_KEY")
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
        # Deliberately do not include repr(e) at unlimited length; provider
        # error surfaces sometimes echo credentials back.
        _fail("openai", f"{type(e).__name__} calling models.list()")
        return False
    ms = (time.perf_counter() - t0) * 1000
    _ok("openai", ms)
    return True


def check_ollama() -> bool:
    base = os.environ.get("OLLAMA_URL", OLLAMA_DEFAULT_URL).rstrip("/")
    url = f"{base}/api/tags"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read(64)
    except urllib.error.HTTPError as e:
        _fail("ollama", f"HTTP {e.code} from {url}")
        return False
    except Exception as e:
        _fail("ollama", f"{type(e).__name__} contacting {url}")
        return False
    ms = (time.perf_counter() - t0) * 1000
    _ok("ollama", ms)
    return True


def check_provider() -> bool:
    provider = os.environ.get("CUE_PROVIDER", "openai").strip().lower()
    if provider == "openai":
        return check_openai()
    if provider == "ollama":
        return check_ollama()
    _fail("provider", f"unknown CUE_PROVIDER={provider!r}; expected openai or ollama")
    return False


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
    provider = os.environ.get("CUE_PROVIDER", "openai").strip().lower() or "openai"
    print(f"smoke_api: provider={provider} (keys are never printed)")
    results = [check_provider(), check_deepgram()]
    if all(results):
        print("all providers reachable.")
        return 0
    print("one or more providers failed; see [FAIL] lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
