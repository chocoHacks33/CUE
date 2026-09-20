from __future__ import annotations

import argparse
import json
from pathlib import Path

from cue_api.release_preflight import (
    FAIL,
    INCOMPLETE,
    Check,
    check_approval,
    check_environment,
    inspect_git,
    inspect_runtime,
    make_manifest,
    run_api_startup_smoke,
    run_provider_smoke,
    run_validation_suite,
    write_manifest,
)


def _default_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify CUE Stage 5 release prerequisites")
    parser.add_argument("--repo-root", type=Path, default=_default_root())
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-suite", action="store_true")
    parser.add_argument("--startup-smoke", action="store_true")
    parser.add_argument("--provider-smoke", action="store_true")
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    env_file = args.env_file or root / ".env"
    approval = args.approval or root / "docs/results/stage5-release-approval.json"
    output = args.output or root / "artifacts/stage5-release-manifest.json"

    commit, checks = inspect_git(root)
    checks.extend(inspect_runtime(root))
    checks.append(check_environment(env_file))
    checks.append(check_approval(approval, commit))
    if args.run_suite:
        checks.extend(run_validation_suite(root))
    else:
        checks.append(Check("validation-suite", INCOMPLETE, "rerun with --run-suite"))
    if args.startup_smoke:
        checks.append(run_api_startup_smoke(root))
    else:
        checks.append(Check("api-clean-start", INCOMPLETE, "rerun with --startup-smoke"))
    if args.provider_smoke:
        checks.append(run_provider_smoke(root))
    else:
        checks.append(Check("provider-smoke", INCOMPLETE, "rerun with --provider-smoke"))

    manifest = make_manifest(commit, checks)
    write_manifest(output, manifest)
    print(json.dumps(manifest, indent=2))
    if manifest["status"] == FAIL:
        return 1
    if manifest["status"] == INCOMPLETE:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
