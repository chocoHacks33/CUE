from __future__ import annotations

import argparse
import json
from pathlib import Path

from cue_api.morning_preflight import (
    FAIL,
    INCOMPLETE,
    Check,
    inspect_repository,
    load_json_object,
    make_report,
    probe_live_api,
    validate_evidence,
    write_report,
)
from cue_api.release_preflight import parse_env_file


def _default_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Person A's Stage 7 morning preflight")
    parser.add_argument("--repo-root", type=Path, default=_default_root())
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout must be between 1 and 30 seconds")

    root = args.repo_root.resolve()
    evidence_path = args.evidence or root / "docs/results/stage7-a-preflight.json"
    env_path = args.env_file or root / ".env"
    output = args.output or root / "artifacts/stage7-a-preflight-report.json"
    commit, branch, checks = inspect_repository(root)

    evidence: dict[str, object] | None = None
    try:
        evidence = load_json_object(evidence_path)
        checks.append(validate_evidence(evidence, commit))
    except ValueError as error:
        checks.append(Check("stage7-evidence", INCOMPLETE, str(error)))

    if args.run_live:
        network = evidence.get("network") if isinstance(evidence, dict) else None
        env = parse_env_file(env_path)
        secret = env.get("CUE_BOOTSTRAP_SECRET", "")
        if not isinstance(network, dict):
            checks.append(Check("live-preflight", INCOMPLETE, "network evidence is missing"))
        elif len(secret) < 24 or "replace" in secret.lower():
            checks.append(
                Check("live-preflight", INCOMPLETE, "usable bootstrap secret is not configured")
            )
        else:
            checks.extend(
                probe_live_api(
                    str(network.get("apiBaseUrl", "")),
                    str(network.get("eventId", "")),
                    secret,
                    timeout=args.timeout,
                )
            )
    else:
        checks.append(Check("live-preflight", INCOMPLETE, "rerun with --run-live on A's laptop"))

    report = make_report(commit, branch, checks, evidence)
    write_report(output, report)
    print(json.dumps(report, indent=2))
    if report["status"] == FAIL:
        return 1
    if report["status"] == INCOMPLETE:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
