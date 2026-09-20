#!/usr/bin/env python3
"""Record the exact Mac configuration behind a run, without any secret value.

v3 plan Stage 5 (D): save the exact Mac configuration. Everything here is
gathered from the machine and rendered as Markdown for the results file. For
environment files it lists variable NAMES only, and which names from
`.env.example` are missing; no value is ever read into the output.

    python scripts/mac_config_snapshot.py [--json] [--out docs/results/private-mac-config.md]
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "fastapi",
    "uvicorn",
    "livekit-api",
    "livekit",
    "opencv-python",
    "numpy",
    "pydantic",
    "openai",
    "deepgram-sdk",
)
PROCESSES = ("uvicorn", "ngrok", "cloudflared", "vite", "node", "Google Chrome")
ENV_FILES = (".env", "apps/api/.env")
ENV_EXAMPLE = ".env.example"


def _run(args: list[str], timeout: float = 10.0) -> str | None:
    if shutil.which(args[0]) is None:
        return None
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def env_names(text: str) -> list[str]:
    """Variable names in a dotenv text. Values are never returned."""
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, _value = line.partition("=")
        name = name.strip()
        if sep and name and all(ch.isalnum() or ch == "_" for ch in name):
            names.append(name)
    return sorted(set(names))


def env_summary(repo_root: Path) -> dict:
    example_path = repo_root / ENV_EXAMPLE
    expected = env_names(example_path.read_text()) if example_path.is_file() else []
    files: dict[str, dict] = {}
    present: set[str] = set()
    for relative in ENV_FILES:
        path = repo_root / relative
        if not path.is_file():
            files[relative] = {"present": False, "names": []}
            continue
        names = env_names(path.read_text())
        present.update(names)
        files[relative] = {"present": True, "names": names}
    return {
        "example": ENV_EXAMPLE if expected else None,
        "expectedNames": expected,
        "files": files,
        "missingFromExample": sorted(name for name in expected if name not in present),
    }


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def git_state(repo_root: Path) -> dict:
    def git(*args: str) -> str | None:
        return _run(["git", "-C", str(repo_root), *args])

    status = git("status", "--porcelain")
    return {
        "branch": git("branch", "--show-current"),
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "tagsAtHead": (git("tag", "--points-at", "HEAD") or "").split() or [],
        "remote": git("remote", "get-url", "origin"),
    }


def macos_facts() -> dict:
    version = _run(["sw_vers", "-productVersion"])
    build = _run(["sw_vers", "-buildVersion"])
    chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    memory = _run(["sysctl", "-n", "hw.memsize"])
    return {
        "productVersion": version,
        "build": build,
        "arch": platform.machine(),
        "chip": chip,
        "memoryGb": round(int(memory) / 1_073_741_824, 1) if memory and memory.isdigit() else None,
    }


def chrome_version() -> str | None:
    plist = Path("/Applications/Google Chrome.app/Contents/Info.plist")
    if not plist.is_file():
        return None
    return _run(["defaults", "read", str(plist), "CFBundleShortVersionString"])


def processes_from_listing(listing: str, expected: tuple[str, ...] = PROCESSES) -> list[str]:
    """Which expected process names appear in a `pgrep -lf` listing. Names only, never arguments."""
    found: set[str] = set()
    for line in listing.splitlines():
        _pid, _, command = line.strip().partition(" ")
        lowered = command.lower()
        for name in expected:
            if name.lower() in lowered:
                found.add(name)
    return sorted(found)


def running_processes() -> list[str]:
    listing = _run(["pgrep", "-l", "-f", "|".join(PROCESSES)])
    return processes_from_listing(listing or "")


def gather(repo_root: Path = REPO_ROOT) -> dict:
    usage = shutil.disk_usage(repo_root)
    ffmpeg = _run(["ffmpeg", "-version"])
    return {
        "capturedAt": datetime.now(UTC).isoformat(),
        "hostname": platform.node(),
        "macos": macos_facts(),
        "disk": {"path": str(repo_root), "freeGb": round(usage.free / 1_073_741_824, 1)},
        "git": git_state(repo_root),
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "packages": package_versions(),
        },
        "node": {"node": _run(["node", "-v"]), "npm": _run(["npm", "-v"])},
        "chrome": chrome_version(),
        "ffmpeg": ffmpeg.splitlines()[0] if ffmpeg else None,
        "env": env_summary(repo_root),
        "processes": running_processes(),
    }


def render(snapshot: dict) -> str:
    macos = snapshot["macos"]
    git = snapshot["git"]
    lines = [
        f"Captured {snapshot['capturedAt']} on {snapshot['hostname']}.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| macOS | {macos['productVersion']} ({macos['build']}) {macos['arch']} |",
        f"| Chip / memory | {macos['chip']} / {macos['memoryGb']} GB |",
        f"| Free disk at repo | {snapshot['disk']['freeGb']} GB |",
        f"| Git | `{git['commit']}` on `{git['branch']}`, {'DIRTY' if git['dirty'] else 'clean'}"
        f"{', tags ' + ', '.join(git['tagsAtHead']) if git['tagsAtHead'] else ', untagged'} |",
        f"| Python | {snapshot['python']['version']} (`{snapshot['python']['executable']}`) |",
    ]
    packages = ", ".join(
        f"{name} {version or 'absent'}" for name, version in snapshot["python"]["packages"].items()
    )
    lines.append(f"| Packages | {packages} |")
    lines.append(f"| Node / npm | {snapshot['node']['node']} / {snapshot['node']['npm']} |")
    lines.append(f"| Chrome | {snapshot['chrome'] or 'not found'} |")
    lines.append(f"| ffmpeg | {snapshot['ffmpeg'] or 'not found'} |")
    env = snapshot["env"]
    for relative, info in env["files"].items():
        value = ", ".join(info["names"]) if info["present"] else "absent"
        lines.append(f"| `{relative}` (names only) | {value} |")
    missing = ", ".join(env["missingFromExample"]) if env["missingFromExample"] else "none"
    lines.append(f"| Missing vs `{env['example'] or 'no example'}` | {missing} |")
    lines.append(
        f"| Running | {', '.join(snapshot['processes']) or 'none of the expected processes'} |"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None, help="write the Markdown here as well")
    args = parser.parse_args(argv)
    snapshot = gather()
    text = json.dumps(snapshot, indent=2) if args.json else render(snapshot)
    if args.out is not None:
        args.out.write_text(render(snapshot) + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
