"""B's offline regression check. No hardware, no network, no venue.

Stage 6 permits "documentation/offline regression checks" and forbids new media
architecture, model migration or major features. This is the offline check: one
command that answers "did anything drift while we were asleep?" in about twenty
seconds, so whoever picks up at 08:00 does not have to reconstruct what good looks
like.

It runs nothing that needs a camera, a Mac, a model file or a network. Model-backed
tests skip themselves when the weights are absent, which is the normal state on a
machine that is not B's.

Exit code is the point: 0 means B's lane is where it was left.

    python scripts/b_offline_regression.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"

#: Prefer the venv B actually uses, so the check does not silently run on a
#: different interpreter than the one the numbers were recorded on.
VENV_PYTHON = API / ".venv" / "Scripts" / "python.exe"
POSIX_VENV_PYTHON = API / ".venv" / "bin" / "python"


def interpreter() -> str:
    for candidate in (VENV_PYTHON, POSIX_VENV_PYTHON):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run(label: str, argv: list[str], cwd: Path) -> tuple[str, bool, str]:
    """Run one check and summarise it in a single line."""
    try:
        finished = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            # pytest's failure output on Windows carries cp1252 bytes (0x97 is an
            # em-dash), which crashed the reader thread and degraded the detail to
            # a bare "exit 1" — losing the diagnostic exactly when it is needed.
            errors="replace",
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return label, False, f"could not run: {error}"

    ok = finished.returncode == 0
    lines = [line.strip() for line in (finished.stdout or "").splitlines() if line.strip()]
    if not ok:
        # On failure prefer a line that names what broke; a blank detail at 08:00
        # is worse than useless.
        named = [
            line
            for line in lines
            if line.startswith(("FAILED", "ERROR", "E ")) or " failed" in line
        ]
        lines = named or lines
        if not lines:
            lines = [line.strip() for line in (finished.stderr or "").splitlines() if line.strip()]
    detail = lines[-1] if ok else (lines[0] if lines else f"exit {finished.returncode}")
    return label, ok, detail[:110]


def guest_tests() -> tuple[str, bool, str]:
    return run(
        "B's tests",
        [interpreter(), "-m", "pytest", "-q", "-k", "guest"],
        API,
    )


def lint() -> tuple[str, bool, str]:
    return run("ruff", [interpreter(), "-m", "ruff", "check", "."], API)


def naming_policy_still_off() -> tuple[str, bool, str]:
    """The load-bearing claim in B's submission. If this drifts, the doc lies."""
    code = (
        "import sys;"
        "sys.path.insert(0, 'src');"
        "from cue_api.guests.confidence_calibration import PROVISIONAL_CALIBRATION as C;"
        "from cue_api.guests.identity_readiness import assess_identity_readiness as a;"
        "r = a(calibration=C);"
        "print(r.policy.value, r.role_based, r.unattended_naming_permitted)"
    )
    label, ok, detail = run("naming policy", [interpreter(), "-c", code], API)
    if not ok:
        return label, False, detail
    expected = "ROLE_BASED True False"
    return label, detail.strip() == expected, detail.strip() or "(no output)"


def doc_links() -> tuple[str, bool, str]:
    """A submission document with a broken link is a bad look at 10:00."""
    import re

    docs = sorted((ROOT / "docs").glob("b-*.md"))
    docs += [ROOT / "docs" / "results" / "b-identity-report.md"]
    docs += [ROOT / "docs" / "results" / "b-media-check.md"]
    broken: list[str] = []
    for doc in docs:
        if not doc.exists():
            broken.append(f"{doc.name} is missing")
            continue
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith("http"):
                continue
            if not (doc.parent / target).resolve().exists():
                broken.append(f"{doc.name} -> {target}")
    if broken:
        return "doc links", False, "; ".join(broken[:3])
    return "doc links", True, f"{len(docs)} documents, every link resolves"


def main() -> int:
    print(f"B offline regression — interpreter {interpreter()}")
    print("(no camera, no Mac, no network; model-backed tests skip without weights)")
    print()

    checks = [guest_tests(), lint(), naming_policy_still_off(), doc_links()]

    width = max(len(label) for label, _, _ in checks)
    for label, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label.ljust(width)}  {detail}")

    failed = [label for label, ok, _ in checks if not ok]
    print()
    if failed:
        print(f"DRIFTED — {', '.join(failed)}. Do not change code to make this pass;")
        print("find out what moved, and whether B's documents are now untrue.")
        return 1
    print("Nothing drifted. B's lane is where it was left.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
