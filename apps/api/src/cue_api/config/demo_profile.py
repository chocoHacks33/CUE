"""Optional demo profile loader.

Reads ``config/demo.example.env`` for defaults (no secrets) and
``config/demo_roster.json`` for the four guests we will really have on
stage. Loaded only when ``CUE_PROFILE=demo`` is exported. The live lane
and desk call :func:`load_demo_profile` at start-up; unset profile is a
no-op so default behaviour is unchanged.

The example env file never carries secret values. Secrets stay in the
git-ignored ``../CUE/.env`` and are read by python-dotenv in the caller.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_ENV_PATH = REPO_ROOT / "config" / "demo.example.env"
DEFAULT_ROSTER_PATH = REPO_ROOT / "config" / "demo_roster.json"


@dataclass(frozen=True)
class DemoProfile:
    """Frozen defaults for the demo profile. Never carries a secret."""
    cue_model: str
    deepgram_model: str
    endpointing_ms: int
    utterance_end_ms: int
    keyterms: tuple[str, ...]
    cue_lifetime_s: float
    min_shot_s: float
    mode_default: str
    role_based: bool
    guests: tuple[dict, ...]
    role_map: dict[str, str]


def _parse_env_defaults(text: str) -> dict[str, str]:
    """Read a ``KEY=VALUE`` env file into a dict. Empty values and lines
    starting with ``#`` are ignored. Never called on the secret .env."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if not v:
            continue
        out[k] = v
    return out


def _read_roster(path: Path) -> tuple[list[dict], dict[str, str]]:
    if not path.exists():
        return [], {}
    data = json.loads(path.read_text(encoding="utf-8"))
    guests = list(data.get("guests") or [])
    role_map = dict(data.get("role_map") or {})
    if len(guests) > 4:
        raise ValueError(
            f"demo_roster.json carries {len(guests)} guests; the demo profile "
            "caps this at four to match the freeze rule."
        )
    return guests, role_map


def _get(env: dict[str, str], name: str, default: str) -> str:
    """Prefer live env var, else the example-env default, else provided."""
    if os.environ.get(name):
        return os.environ[name]
    return env.get(name, default)


def load_demo_profile(
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    roster_path: Path = DEFAULT_ROSTER_PATH,
) -> DemoProfile | None:
    """Return the demo profile if ``CUE_PROFILE=demo``. Else ``None``.

    Never modifies os.environ. Never reads a secret. Callers wire the
    knobs into their own subsystems (Deepgram builder, director, etc).
    """
    if os.environ.get("CUE_PROFILE", "").lower() != "demo":
        return None
    env_defaults: dict[str, str] = {}
    if env_path.exists():
        env_defaults = _parse_env_defaults(env_path.read_text(encoding="utf-8"))
    # A defensive check: an operator who copies the example env to a real
    # env file may accidentally paste a key. We NEVER read the secret
    # fields here, so it doesn't matter — but we assert their names are
    # not in the returned profile.
    for secret in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY"):
        env_defaults.pop(secret, None)
    guests, role_map = _read_roster(roster_path)
    keyterms_raw = _get(env_defaults, "DEEPGRAM_KEYTERMS", "")
    keyterms = tuple(
        k.strip() for k in keyterms_raw.split(",") if k.strip()
    )
    return DemoProfile(
        cue_model=_get(env_defaults, "CUE_MODEL", ""),
        deepgram_model=_get(env_defaults, "DEEPGRAM_MODEL", "nova-3"),
        endpointing_ms=int(_get(env_defaults, "DEEPGRAM_ENDPOINTING_MS", "300")),
        utterance_end_ms=int(_get(env_defaults, "DEEPGRAM_UTTERANCE_END_MS", "1000")),
        keyterms=keyterms,
        cue_lifetime_s=float(_get(env_defaults, "CUE_LIFETIME_S", "3.0")),
        min_shot_s=float(_get(env_defaults, "MIN_SHOT_S", "2.5")),
        mode_default=_get(env_defaults, "CUE_MODE_DEFAULT", "ASSIST").upper(),
        role_based=_get(env_defaults, "CUE_ROLE_BASED", "1") not in ("0", "false", "False", ""),
        guests=tuple(guests),
        role_map=role_map,
    )


def as_public_dict(profile: DemoProfile) -> dict[str, Any]:
    """Return a JSON-safe dict view of the profile. Callers hand this to
    the desk / status endpoints. Never includes secrets."""
    return {
        "cue_model": profile.cue_model,
        "deepgram_model": profile.deepgram_model,
        "endpointing_ms": profile.endpointing_ms,
        "utterance_end_ms": profile.utterance_end_ms,
        "keyterms": list(profile.keyterms),
        "cue_lifetime_s": profile.cue_lifetime_s,
        "min_shot_s": profile.min_shot_s,
        "mode_default": profile.mode_default,
        "role_based": profile.role_based,
        "guests": [dict(g) for g in profile.guests],
        "role_map": dict(profile.role_map),
    }
