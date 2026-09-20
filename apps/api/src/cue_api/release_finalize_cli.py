from __future__ import annotations

import argparse
from pathlib import Path

from cue_api.release_finalize import (
    load_json_object,
    validate_release_inputs,
    verify_repository,
)
from cue_api.release_preflight import PASS, check_approval, git_value, run_command


def _default_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely finalize a passing CUE release")
    parser.add_argument("--repo-root", type=Path, default=_default_root())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--create-tag", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args(argv)
    if args.push and not args.create_tag:
        print("release refused: --push requires --create-tag")
        return 2
    root = args.repo_root.resolve()
    manifest_path = args.manifest or root / "artifacts/stage5-release-manifest.json"
    approval_path = args.approval or root / "docs/results/stage5-release-approval.json"

    try:
        head = git_value(root, "rev-parse", "HEAD")
        manifest = load_json_object(manifest_path, "release manifest")
        approval = load_json_object(approval_path, "release approval")
        approval_check = check_approval(approval_path, head)
        if approval_check.status != PASS:
            raise ValueError(approval_check.detail)
        inputs = validate_release_inputs(manifest, approval, head)
        verify_repository(root, inputs)
    except (RuntimeError, ValueError) as error:
        print(f"release refused: {error}")
        return 2

    if not args.create_tag:
        print(
            f"release validated: {inputs.tag} at {inputs.commit} ({inputs.mode}); "
            "rerun with --create-tag after human review"
        )
        return 0

    message = f"CUE HackMIT 2026 release ({inputs.mode})"
    created = run_command(["git", "tag", "-a", inputs.tag, "-m", message], root, timeout=30)
    if created.returncode != 0:
        print("release refused: annotated tag creation failed")
        return 2
    print(f"created annotated tag {inputs.tag} at {inputs.commit}")

    if args.push:
        pushed = run_command(
            ["git", "push", "origin", f"refs/tags/{inputs.tag}"], root, timeout=60
        )
        if pushed.returncode != 0:
            print("tag exists locally but push failed; inspect before retrying")
            return 1
        print(f"pushed {inputs.tag} to origin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
