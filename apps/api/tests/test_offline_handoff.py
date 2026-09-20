from __future__ import annotations

import subprocess
from pathlib import Path

from cue_api.offline_handoff import (
    FAIL,
    INCOMPLETE,
    PASS,
    Check,
    make_report,
    offline_commands,
    run_offline_suite,
    validate_handoff,
)


def valid_handoff(commit: str = "abc123") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "commit": commit,
        "fromOwner": "A",
        "toOwner": "D",
        "releaseMode": "ROLE_BASED_ASSIST",
        "hardwareStatus": "NEEDS_REVALIDATION",
        "resumeAtUtc": "2026-09-20T12:00:00Z",
        "knownBlockers": ["Three-camera Mac run remains unverified"],
        "morningFirstActions": ["Reframe and reconnect all three cameras"],
        "completedOfflineWork": ["Backend and web regression suite"],
        "acknowledgements": {
            "noNewMediaArchitecture": True,
            "noModelMigration": True,
            "noHardwareClaim": True,
            "venueRulesChecked": True,
            "handoffAgreed": True,
        },
    }


def test_valid_handoff_is_exact_commit_and_explicitly_unverified() -> None:
    assert validate_handoff(valid_handoff(), "abc123").status == PASS
    mismatch = validate_handoff(valid_handoff(), "different")
    assert mismatch.status == INCOMPLETE
    assert "does not equal HEAD" in mismatch.detail


def test_handoff_cannot_claim_hardware_validation() -> None:
    value = valid_handoff()
    value["hardwareStatus"] = "PASS"
    result = validate_handoff(value, "abc123")
    assert result.status == INCOMPLETE
    assert "NEEDS_REVALIDATION" in result.detail


def test_secret_like_fields_are_refused() -> None:
    value = valid_handoff()
    value["apiKey"] = "must-never-be-here"
    result = validate_handoff(value, "abc123")
    assert result.status == INCOMPLETE
    assert "forbidden" in result.detail


def test_offline_command_list_has_no_external_or_mutating_steps(tmp_path: Path) -> None:
    flattened = " ".join(part for _, command, _ in offline_commands(tmp_path) for part in command)
    lowered = flattened.lower()
    for forbidden in ("openai", "deepgram", "curl", "pip install", "npm ci", "git push", "git tag"):
        assert forbidden not in lowered


def test_suite_removes_provider_credentials_from_child_environment(tmp_path: Path) -> None:
    seen_environments: list[dict[str, str]] = []

    def runner(
        command: list[str], cwd: Path, timeout: int, environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout
        seen_environments.append(environment)
        return subprocess.CompletedProcess(command, 0, "", "")

    results = run_offline_suite(tmp_path, runner=runner)
    assert all(result.status == PASS for result in results)
    assert len(seen_environments) == 5
    assert all(environment.get("CUE_OFFLINE") == "1" for environment in seen_environments)
    assert all("OPENAI_API_KEY" not in environment for environment in seen_environments)
    assert all("DEEPGRAM_API_KEY" not in environment for environment in seen_environments)
    assert all("LIVEKIT_API_SECRET" not in environment for environment in seen_environments)
    assert all("CUE_PRODUCER_SECRET" not in environment for environment in seen_environments)


def test_report_can_never_certify_hardware_or_release() -> None:
    report = make_report(
        "abc123",
        "codex/person-a-stage-6-prep",
        [Check("offline", PASS, "passed")],
        valid_handoff(),
    )
    assert report["status"] == PASS
    assert report["offlineRegressionPassed"] is True
    assert report["hardwareValidated"] is False
    assert report["releaseCertified"] is False


def test_failure_takes_priority_over_incomplete() -> None:
    report = make_report(
        "abc123",
        "branch",
        [Check("handoff", INCOMPLETE, "missing"), Check("tests", FAIL, "failed")],
        None,
    )
    assert report["status"] == FAIL
