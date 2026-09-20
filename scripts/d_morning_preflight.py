#!/usr/bin/env python3
"""D's Sunday morning preflight: everything the Mac can check before any claim.

v3 plan Stage 7 (D): recheck all mappings, A's audio, clap and flash timing, a
final soak and recording playback, then rehearse; the exit gate is that claims
match today's conditions. The physical rows need eyes and hands. This command
does the checkable part in one go against the running backend and prints the
physical rows as reminders, so nothing is claimed from habit.

It reads the producer and bootstrap secrets from the root `.env` to call the
backend's read routes and never prints them.

    python scripts/d_morning_preflight.py --api http://127.0.0.1:8000 --event hackmit-demo
        [--commit <sha> | --tag cue-hackmit-2026-demo]
        [--worker-python .venv/bin/python] [--recordings-dir ~/Movies] [--offline] [--json]

Exit 0 only when every automated check is GO. Physical rows are listed, never counted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMERAS = ("CAM-HOST", "CAM-GUEST", "CAM-WIDE")
REQUIRED_ENV = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "CUE_BOOTSTRAP_SECRET",
    "CUE_PRODUCER_SECRET",
    "OPENAI_API_KEY",
    "DEEPGRAM_API_KEY",
    "CUE_MODEL",
)
DEFAULT_TAG = "cue-hackmit-2026-demo"
MIN_FREE_GB = 5.0

GO, NO_GO, SKIP, MANUAL = "GO", "NO-GO", "SKIP", "MANUAL"

Fetch = Callable[[str, dict[str, str]], tuple[int, object]]


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""

    def line(self) -> str:
        mark = {GO: "GO   ", NO_GO: "NO-GO", SKIP: "SKIP ", MANUAL: "MANUAL"}[self.status]
        return f"[{mark}] {self.name}" + (f"  ({self.detail})" if self.detail else "")


# ---------------------------------------------------------------- inputs


def parse_env(text: str) -> dict[str, str]:
    """dotenv text to a mapping. Values stay in memory and are never printed."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def default_fetch(url: str, headers: dict[str, str]) -> tuple[int, object]:
    request = urllib.request.Request(url, headers={**headers, "ngrok-skip-browser-warning": "1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        body = error.read()
        status = error.code
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(error)
    try:
        return status, json.loads(body or b"null")
    except json.JSONDecodeError:
        return status, None


# ---------------------------------------------------------------- checks


def check_commit(
    git: Callable[[list[str]], str | None], expected: str | None, tag: str | None
) -> Check:
    head = git(["rev-parse", "HEAD"]) or ""
    dirty = git(["status", "--porcelain"])
    short = head[:7] or "unknown"
    if dirty:
        return Check("frozen commit", NO_GO, f"working tree is dirty at {short}")
    if expected:
        if head.startswith(expected) or expected.startswith(head):
            return Check("frozen commit", GO, f"HEAD {short} is the expected candidate, tree clean")
        return Check("frozen commit", NO_GO, f"HEAD {short} is not the expected {expected[:7]}")
    if tag:
        tagged = git(["rev-list", "-n", "1", tag])
        if not tagged:
            return Check(
                "frozen commit", NO_GO, f"tag {tag} does not exist; HEAD {short}, tree clean"
            )
        if tagged.strip() == head:
            return Check("frozen commit", GO, f"HEAD {short} is tag {tag}, tree clean")
        return Check("frozen commit", NO_GO, f"HEAD {short} is not tag {tag} ({tagged[:7]})")
    return Check("frozen commit", GO, f"HEAD {short}, tree clean (no expected commit given)")


def check_env_names(values: dict[str, str]) -> Check:
    missing = [name for name in REQUIRED_ENV if not values.get(name, "").strip()]
    if missing:
        return Check("env populated", NO_GO, "empty or missing: " + ", ".join(missing))
    return Check("env populated", GO, f"{len(REQUIRED_ENV)} names populated; values not shown")


def check_worker_python(python: Path, run: Callable[[list[str]], int]) -> Check:
    if not python.exists():
        return Check("worker venv has livekit", NO_GO, f"{python} not found")
    code = run([str(python), "-c", "import livekit.rtc"])
    if code == 0:
        return Check("worker venv has livekit", GO, str(python))
    return Check("worker venv has livekit", NO_GO, f"import livekit.rtc failed in {python}")


def check_tools(which: Callable[[str], str | None]) -> Check:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if which(tool) is None]
    if missing:
        return Check("ffmpeg and ffprobe", NO_GO, "missing: " + ", ".join(missing))
    return Check("ffmpeg and ffprobe", GO, "on PATH for verify_recording and av_skew")


def check_disk(path: Path, free_bytes: int, min_gb: float = MIN_FREE_GB) -> Check:
    free_gb = free_bytes / 1_073_741_824
    if free_gb < min_gb:
        return Check("free disk for recordings", NO_GO, f"{free_gb:.1f} GB free at {path}")
    return Check("free disk for recordings", GO, f"{free_gb:.1f} GB free at {path}")


def _api(api: str, path: str) -> str:
    return f"{api.rstrip('/')}{path}"


def check_api_ready(fetch: Fetch, api: str) -> Check:
    status, body = fetch(_api(api, "/health/ready"), {})
    if status == 200 and isinstance(body, dict) and body.get("status") == "ready":
        return Check("API ready", GO, f"{api} ready, LiveKit configured")
    return Check("API ready", NO_GO, f"{api} returned {status}: {str(body)[:80]}")


def check_bindings(fetch: Fetch, api: str, event: str, producer_secret: str) -> Check:
    status, body = fetch(
        _api(api, f"/api/v1/events/{event}/bindings"), {"X-CUE-Producer-Secret": producer_secret}
    )
    if status != 200 or not isinstance(body, list):
        return Check("three cameras bound", NO_GO, f"bindings returned {status}")
    bound: dict[str, dict] = {}
    for item in body:
        if isinstance(item, dict) and item.get("cameraId") in CAMERAS:
            bound[item["cameraId"]] = item
    missing = [camera for camera in CAMERAS if camera not in bound]
    if missing:
        return Check("three cameras bound", NO_GO, "not bound: " + ", ".join(missing))
    identities = {item.get("participantIdentity") for item in bound.values()}
    if len(identities) != len(CAMERAS):
        return Check("three cameras bound", NO_GO, "two cameras share one publisher identity")
    no_track = [camera for camera, item in bound.items() if not item.get("currentVideoTrackSid")]
    if no_track:
        return Check(
            "three cameras bound", NO_GO, "bound but no video track: " + ", ".join(no_track)
        )
    epochs = ", ".join(f"{camera} e{bound[camera].get('streamEpoch')}" for camera in CAMERAS)
    return Check("three cameras bound", GO, epochs)


def check_receiver(
    fetch: Fetch, api: str, event: str, producer_secret: str, sleep: Callable[[float], None]
) -> Check:
    url = _api(api, f"/api/v1/events/{event}/readiness")
    headers = {"X-CUE-Producer-Secret": producer_secret}
    status, first = fetch(url, headers)
    if status != 200 or not isinstance(first, dict):
        return Check(
            "compositor readiness live", NO_GO, f"readiness returned {status}: no report yet"
        )
    sleep(1.0)
    status, second = fetch(url, headers)
    if status != 200 or not isinstance(second, dict):
        return Check("compositor readiness live", NO_GO, f"second read returned {status}")
    if second.get("reportedAtMs") == first.get("reportedAtMs"):
        return Check(
            "compositor readiness live", NO_GO, "report did not advance in 1 s: stale compositor"
        )
    problems: list[str] = []
    if int(second.get("rendererGeneration") or 0) < 1:
        problems.append("renderer generation 0")
    slots = {
        slot.get("cameraId"): slot for slot in second.get("slots", []) if isinstance(slot, dict)
    }
    for camera in CAMERAS:
        slot = slots.get(camera)
        if not slot or not slot.get("renderable"):
            problems.append(f"{camera} not renderable")
        elif not slot.get("framesProgressing"):
            problems.append(f"{camera} frames not progressing")
    audio = second.get("masterAudio") or {}
    if not audio.get("attached"):
        problems.append("master audio not attached")
    if second.get("currentSource") is None:
        problems.append("compositor has not drawn anything")
    if problems:
        return Check("compositor readiness live", NO_GO, "; ".join(problems))
    return Check(
        "compositor readiness live",
        GO,
        "3 renderable, frames progressing, master audio attached, "
        f"on air {second.get('currentSource')}",
    )


def check_control(fetch: Fetch, api: str, event: str, producer_secret: str) -> Check:
    status, body = fetch(
        _api(api, f"/api/v1/events/{event}/control-state"),
        {"X-CUE-Producer-Secret": producer_secret},
    )
    if status != 200 or not isinstance(body, dict):
        return Check("control state", NO_GO, f"control-state returned {status}")
    mode = body.get("mode")
    if mode == "AUTO":
        return Check("control state", NO_GO, "AUTO is armed before validation; go back to ASSIST")
    if mode == "ENDED":
        return Check("control state", NO_GO, "event is ENDED; start a fresh event")
    if body.get("pendingDecisionId"):
        return Check("control state", NO_GO, f"a render is pending acknowledgement in {mode}")
    return Check(
        "control state",
        GO,
        f"{mode}, generation {body.get('controlGeneration')}, revision {body.get('modeRevision')}",
    )


def check_identity(fetch: Fetch, api: str, event: str, bootstrap_secret: str, today: date) -> Check:
    status, body = fetch(
        _api(api, f"/api/v1/guests/readiness?eventId={event}"),
        {"X-CUE-Bootstrap-Secret": bootstrap_secret},
    )
    if status != 200 or not isinstance(body, dict):
        return Check("naming policy and disclosure", NO_GO, f"guests/readiness returned {status}")
    policy = body.get("namingPolicy")
    disclosure = str(body.get("disclosure") or "").strip()
    if not disclosure:
        return Check("naming policy and disclosure", NO_GO, "empty disclosure cannot be shown")
    validation = body.get("morningValidation")
    filed_today = (
        isinstance(validation, dict)
        and validation.get("validatedOn") == today.isoformat()
        and bool(validation.get("allPassed"))
    )
    if policy != "ROLE_BASED" and not filed_today:
        return Check(
            "naming policy and disclosure",
            NO_GO,
            f"{policy} without B's morning validation passed today; names cannot be shown",
        )
    note = (
        "B's morning validation filed today"
        if filed_today
        else "B's morning validation not filed today"
    )
    return Check("naming policy and disclosure", GO, f"{policy}; {note}; disclosure: {disclosure}")


def check_stage4_report(fetch: Fetch, api: str, event: str, producer_secret: str) -> Check:
    status, body = fetch(
        _api(api, f"/api/v1/events/{event}/stage4/report"),
        {"X-CUE-Producer-Secret": producer_secret},
    )
    if status != 200 or not isinstance(body, dict):
        return Check("A's Stage 4 evidence route", NO_GO, f"stage4/report returned {status}")
    trials = body.get("trials") or []
    assessment = body.get("assessment") or {}
    summary = ", ".join(
        f"{key}={value}" for key, value in assessment.items() if not isinstance(value, list | dict)
    )
    return Check(
        "A's Stage 4 evidence route", GO, f"{len(trials)} trial(s) retained; {summary[:120]}"
    )


def physical_rows() -> list[Check]:
    return [
        Check("mapping: each laptop shows its number, tile matches CAM-HOST/GUEST/WIDE", MANUAL),
        Check("A's audio audible on headphones; one master track in the log; no other mic", MANUAL),
        Check("clap and flash per angle: scripts/av_skew.py on a short recording", MANUAL),
        Check("final soak: 20 minutes if time allows, export the measurements", MANUAL),
        Check(
            "official recording: scripts/verify_recording.py, then play it in VLC or Chrome", MANUAL
        ),
        Check("pitch rehearsal with the live segment from docs/DEMO-D.md, timed", MANUAL),
    ]


# ---------------------------------------------------------------- driver


@dataclass(frozen=True)
class Config:
    api: str
    event: str
    expected_commit: str | None
    tag: str | None
    worker_python: Path
    recordings_dir: Path
    offline: bool


@dataclass(frozen=True)
class Deps:
    env: dict[str, str]
    fetch: Fetch
    git: Callable[[list[str]], str | None]
    run: Callable[[list[str]], int]
    which: Callable[[str], str | None]
    free_bytes: Callable[[Path], int]
    sleep: Callable[[float], None]
    today: date


def run_checks(config: Config, deps: Deps) -> list[Check]:
    checks = [
        check_commit(deps.git, config.expected_commit, config.tag),
        check_env_names(deps.env),
        check_worker_python(config.worker_python, deps.run),
        check_tools(deps.which),
        check_disk(config.recordings_dir, deps.free_bytes(config.recordings_dir)),
    ]
    producer = deps.env.get("CUE_PRODUCER_SECRET", "")
    bootstrap = deps.env.get("CUE_BOOTSTRAP_SECRET", "")
    if config.offline:
        checks.append(Check("backend checks", SKIP, "--offline"))
    else:
        checks.append(check_api_ready(deps.fetch, config.api))
        checks.append(check_bindings(deps.fetch, config.api, config.event, producer))
        checks.append(check_receiver(deps.fetch, config.api, config.event, producer, deps.sleep))
        checks.append(check_control(deps.fetch, config.api, config.event, producer))
        checks.append(check_identity(deps.fetch, config.api, config.event, bootstrap, deps.today))
        checks.append(check_stage4_report(deps.fetch, config.api, config.event, producer))
    checks.extend(physical_rows())
    return checks


def verdict(checks: list[Check]) -> tuple[bool, str]:
    failed = [check for check in checks if check.status == NO_GO]
    manual = [check for check in checks if check.status == MANUAL]
    if failed:
        return (
            False,
            f"NO-GO: {len(failed)} automated check(s) failed; "
            f"{len(manual)} physical rows still NOT RUN",
        )
    return (
        True,
        f"GO on every automated check; {len(manual)} physical rows still NOT RUN until you do them",
    )


def render(checks: list[Check], summary: str) -> str:
    return "\n".join(check.line() for check in checks) + f"\n\nVERDICT: {summary}"


def _git(repo_root: Path) -> Callable[[list[str]], str | None]:
    def run(args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), *args], capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    return run


def _run(args: list[str]) -> int:
    try:
        return subprocess.run(args, capture_output=True, timeout=30).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--event", default="hackmit-demo")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--commit", default=None, help="expected candidate commit")
    parser.add_argument("--tag", default=DEFAULT_TAG, help="release tag to compare HEAD with")
    parser.add_argument("--no-tag", action="store_true", help="do not compare with a tag")
    parser.add_argument(
        "--worker-python", type=Path, default=REPO_ROOT / ".venv" / "bin" / "python"
    )
    parser.add_argument("--recordings-dir", type=Path, default=Path.home() / "Movies")
    parser.add_argument("--offline", action="store_true", help="skip backend checks")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    env_text = args.env_file.read_text() if args.env_file.is_file() else ""
    config = Config(
        api=args.api,
        event=args.event,
        expected_commit=args.commit,
        tag=None if args.no_tag or args.commit else args.tag,
        worker_python=args.worker_python,
        recordings_dir=args.recordings_dir,
        offline=args.offline,
    )
    deps = Deps(
        env=parse_env(env_text),
        fetch=default_fetch,
        git=_git(REPO_ROOT),
        run=_run,
        which=shutil.which,
        free_bytes=lambda path: shutil.disk_usage(path if path.exists() else Path.home()).free,
        sleep=time.sleep,
        today=date.today(),
    )
    checks = run_checks(config, deps)
    ok, summary = verdict(checks)
    if args.json:
        print(
            json.dumps(
                {"ok": ok, "verdict": summary, "checks": [asdict(c) for c in checks]}, indent=2
            )
        )
    else:
        print(render(checks, summary))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
