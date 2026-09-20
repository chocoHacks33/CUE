from __future__ import annotations

import argparse
import json
from pathlib import Path

from cue_api.offline_handoff import (
    FAIL,
    INCOMPLETE,
    Check,
    inspect_repository,
    load_handoff,
    make_report,
    run_offline_suite,
    validate_handoff,
    write_report,
)


def _default_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded CUE Stage 6 offline handoff")
    parser.add_argument("--repo-root", type=Path, default=_default_root())
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-suite", action="store_true")
    parser.add_argument("--maximum-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    if not 60 <= args.maximum_seconds <= 1_800:
        parser.error("--maximum-seconds must be between 60 and 1800")

    root = args.repo_root.resolve()
    handoff_path = args.handoff or root / "docs/results/stage6-handoff.json"
    output = args.output or root / "artifacts/stage6-offline-report.json"
    commit, branch, checks = inspect_repository(root)

    handoff: dict[str, object] | None = None
    try:
        handoff = load_handoff(handoff_path)
        checks.append(validate_handoff(handoff, commit))
    except ValueError as error:
        checks.append(Check("handoff", INCOMPLETE, str(error)))

    if args.run_suite:
        checks.extend(run_offline_suite(root, maximum_seconds=args.maximum_seconds))
    else:
        checks.append(Check("offline-suite", INCOMPLETE, "rerun with --run-suite"))

    report = make_report(commit, branch, checks, handoff)
    write_report(output, report)
    print(json.dumps(report, indent=2))
    if report["status"] == FAIL:
        return 1
    if report["status"] == INCOMPLETE:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
