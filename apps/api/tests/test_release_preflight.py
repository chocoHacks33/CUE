from __future__ import annotations

import json
from pathlib import Path

from cue_api.release_preflight import (
    FAIL,
    INCOMPLETE,
    PASS,
    Check,
    check_approval,
    check_environment,
    check_web_artifact,
    make_manifest,
    parse_env_file,
    run_api_startup_smoke,
)


def valid_approval(commit: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "testedCommit": commit,
        "releaseTag": "cue-hackmit-2026-demo",
        "releaseMode": "ROLE_BASED_ASSIST",
        "scopeDecisionEvidence": "docs/results/stage-4-integration-check.md",
        "stage4Gates": {
            owner: {"status": "PASS", "evidence": f"private/{owner}-stage4.json"}
            for owner in "ABCD"
        },
        "macValidation": {
            "cleanStartup": True,
            "threeFeeds": True,
            "recordingPlayback": True,
            "runbookVerified": True,
        },
        "submission": {
            "saved": True,
            "reopenedAndVerified": True,
            "allMembersVerified": True,
            "trackVerified": True,
            "projectUrl": "https://example.invalid/cue",
            "savedAtUtc": "2026-09-20T02:00:00Z",
            "evidence": "private/submission-reopened.png",
        },
        "ownerSignoffs": {owner: True for owner in "ABCD"},
        "limitationsReviewed": True,
    }


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_env_parser_handles_export_comments_and_quotes(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# comment\nexport ONE='first'\nTWO=second\n", encoding="utf-8")
    assert parse_env_file(path) == {"ONE": "first", "TWO": "second"}


def test_environment_check_never_returns_secret_values(tmp_path: Path) -> None:
    secret = "a-secret-that-must-not-be-logged"
    values = {
        "OPENAI_API_KEY": secret,
        "DEEPGRAM_API_KEY": "dg-secret",
        "LIVEKIT_URL": "wss://cue.livekit.cloud",
        "LIVEKIT_API_KEY": "lk-key",
        "LIVEKIT_API_SECRET": "lk-secret",
        "CUE_MODEL": "configured-model",
        "CUE_BOOTSTRAP_SECRET": "bootstrap-secret-long-enough",
        "CUE_PRODUCER_SECRET": "producer-secret-is-also-long",
        "VITE_API_BASE_URL": "https://cue.invalid",
        "CUE_PROVIDER": "openai",
    }
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    result = check_environment(path)
    assert result.status == PASS
    assert secret not in result.detail


def test_environment_rejects_placeholders_and_reused_secrets(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=replace-me",
                "DEEPGRAM_API_KEY=dg",
                "LIVEKIT_URL=wss://cue.livekit.cloud",
                "LIVEKIT_API_KEY=key",
                "LIVEKIT_API_SECRET=secret",
                "CUE_MODEL=model",
                "CUE_BOOTSTRAP_SECRET=same",
                "CUE_PRODUCER_SECRET=same",
                "VITE_API_BASE_URL=https://cue.invalid",
            ]
        ),
        encoding="utf-8",
    )
    result = check_environment(path)
    assert result.status == FAIL
    assert "placeholder" in result.detail
    assert "must differ" in result.detail


def test_release_approval_is_bound_to_the_exact_commit(tmp_path: Path) -> None:
    path = write_json(tmp_path / "approval.json", valid_approval("abc123"))
    assert check_approval(path, "abc123").status == PASS
    mismatch = check_approval(path, "different")
    assert mismatch.status == INCOMPLETE
    assert "does not equal HEAD" in mismatch.detail


def test_every_owner_gate_and_signoff_is_required(tmp_path: Path) -> None:
    value = valid_approval("abc123")
    value["stage4Gates"]["B"]["status"] = "INCOMPLETE"  # type: ignore[index]
    value["ownerSignoffs"]["D"] = False  # type: ignore[index]
    result = check_approval(write_json(tmp_path / "approval.json", value), "abc123")
    assert result.status == INCOMPLETE
    assert "owner B" in result.detail
    assert "ownerSignoffs.D" in result.detail


def test_manifest_is_fail_closed() -> None:
    incomplete = make_manifest("abc", [Check("gate", INCOMPLETE, "pending")])
    failed = make_manifest(
        "abc",
        [Check("gate", INCOMPLETE, "pending"), Check("tests", FAIL, "failed")],
    )
    passed = make_manifest("abc", [Check("gate", PASS, "done")])
    assert incomplete["releaseReady"] is False
    assert failed["status"] == FAIL
    assert passed["releaseReady"] is True


def test_web_artifact_requires_every_referenced_asset(tmp_path: Path) -> None:
    dist = tmp_path / "apps/web/dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script src="/assets/app.js"></script><link href="/assets/app.css">',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("", encoding="utf-8")
    assert check_web_artifact(tmp_path).status == FAIL
    (assets / "app.css").write_text("", encoding="utf-8")
    assert check_web_artifact(tmp_path).status == PASS


def test_fresh_api_process_reaches_readiness(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")
    repo_root = Path(__file__).resolve().parents[3]
    assert run_api_startup_smoke(repo_root).status == PASS
