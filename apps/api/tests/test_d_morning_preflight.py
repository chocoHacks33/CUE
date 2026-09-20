"""scripts/d_morning_preflight.py against a fake backend. No network, no secrets printed."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import d_morning_preflight as pre  # noqa: E402

TODAY = date(2026, 9, 20)
PRODUCER = "producer-secret-value-0123456789abcdef"
BOOTSTRAP = "bootstrap-secret-value-0123456789abcdef"
ENV = {name: "x" for name in pre.REQUIRED_ENV} | {
    "CUE_PRODUCER_SECRET": PRODUCER,
    "CUE_BOOTSTRAP_SECRET": BOOTSTRAP,
}


def readiness(reported_at: int, **overrides):
    body = {
        "reportedAtMs": reported_at,
        "rendererGeneration": 1,
        "currentSource": "CAM-HOST",
        "masterAudio": {"attached": True},
        "slots": [
            {"cameraId": camera, "renderable": True, "framesProgressing": True}
            for camera in pre.CAMERAS
        ],
    }
    body.update(overrides)
    return body


def good_backend(overrides: dict | None = None):
    """A fetcher over a healthy backend; overrides map a path prefix to (status, body)."""
    overrides = overrides or {}
    reads = {"count": 0}

    def fetch(url: str, headers: dict[str, str]):
        path = url.split("http://api", 1)[1]
        for prefix, response in overrides.items():
            if path.startswith(prefix):
                return response
        if path == "/health/ready":
            return 200, {"status": "ready", "livekitConfigured": True}
        if path.endswith("/bindings"):
            assert headers["X-CUE-Producer-Secret"] == PRODUCER
            return 200, [
                {
                    "cameraId": camera,
                    "participantIdentity": f"pub-{camera}",
                    "streamEpoch": 2,
                    "currentVideoTrackSid": f"TR_{camera}",
                }
                for camera in pre.CAMERAS
            ]
        if path.endswith("/readiness") and "guests" not in path:
            reads["count"] += 1
            return 200, readiness(1000 + reads["count"])
        if path.endswith("/control-state"):
            return 200, {
                "mode": "ASSIST",
                "controlGeneration": "gen-1",
                "modeRevision": 4,
                "pendingDecisionId": None,
            }
        if "/guests/readiness" in path:
            assert headers["X-CUE-Bootstrap-Secret"] == BOOTSTRAP
            return 200, {
                "namingPolicy": "ROLE_BASED",
                "disclosure": "Cameras are chosen by role.",
                "morningValidation": None,
            }
        if path.endswith("/stage4/report"):
            return 200, {
                "trials": [],
                "assessment": {"status": "INCOMPLETE", "mode": "ROLE_BASED_ASSIST"},
            }
        return 404, None

    return fetch


def deps(fetch, env=ENV, dirty=False, tag_sha="abc123def456", head="abc123def456"):
    def git(args):
        if args[:2] == ["rev-parse", "HEAD"]:
            return head
        if args[:2] == ["status", "--porcelain"]:
            return " M x" if dirty else ""
        if args[:2] == ["rev-list", "-n"]:
            return tag_sha
        return None

    return pre.Deps(
        env=env,
        fetch=fetch,
        git=git,
        run=lambda args: 0,
        which=lambda tool: f"/usr/bin/{tool}",
        free_bytes=lambda path: 50 * 1_073_741_824,
        sleep=lambda seconds: None,
        today=TODAY,
    )


CONFIG = pre.Config(
    api="http://api",
    event="hackmit-demo",
    expected_commit=None,
    tag="cue-hackmit-2026-demo",
    worker_python=Path(sys.executable),
    recordings_dir=Path.home(),
    offline=False,
)


def statuses(checks):
    return {check.name: check.status for check in checks}


def test_everything_go_on_a_healthy_morning_and_physical_rows_are_listed_not_counted():
    checks = pre.run_checks(CONFIG, deps(good_backend()))
    automated = [check for check in checks if check.status != pre.MANUAL]
    assert all(check.status == pre.GO for check in automated), statuses(checks)
    assert len([check for check in checks if check.status == pre.MANUAL]) == 6
    ok, summary = pre.verdict(checks)
    assert ok and "6 physical rows still NOT RUN" in summary


def test_no_secret_value_ever_appears_in_output():
    checks = pre.run_checks(CONFIG, deps(good_backend()))
    text = pre.render(checks, pre.verdict(checks)[1]) + json.dumps([asdict(c) for c in checks])
    assert PRODUCER not in text and BOOTSTRAP not in text


def test_parse_env_keeps_values_in_memory_and_strips_quotes():
    values = pre.parse_env('# c\nexport A="one"\nB=two\nC=\nnot a line\n')
    assert values == {"A": "one", "B": "two", "C": ""}
    assert pre.check_env_names(values).status == pre.NO_GO
    assert "CUE_MODEL" in pre.check_env_names(values).detail


def test_missing_binding_and_shared_identity_are_no_go():
    missing = good_backend(
        {
            "/api/v1/events/hackmit-demo/bindings": (
                200,
                [
                    {
                        "cameraId": "CAM-HOST",
                        "participantIdentity": "p1",
                        "streamEpoch": 1,
                        "currentVideoTrackSid": "TR1",
                    },
                ],
            )
        }
    )
    assert statuses(pre.run_checks(CONFIG, deps(missing)))["three cameras bound"] == pre.NO_GO
    shared = good_backend(
        {
            "/api/v1/events/hackmit-demo/bindings": (
                200,
                [
                    {
                        "cameraId": camera,
                        "participantIdentity": "same",
                        "streamEpoch": 1,
                        "currentVideoTrackSid": f"T{camera}",
                    }
                    for camera in pre.CAMERAS
                ],
            )
        }
    )
    check = [c for c in pre.run_checks(CONFIG, deps(shared)) if c.name == "three cameras bound"][0]
    assert check.status == pre.NO_GO and "share" in check.detail


def test_stale_compositor_report_is_no_go():
    frozen = good_backend({"/api/v1/events/hackmit-demo/readiness": (200, readiness(5000))})
    check = [
        c for c in pre.run_checks(CONFIG, deps(frozen)) if c.name == "compositor readiness live"
    ][0]
    assert check.status == pre.NO_GO and "did not advance" in check.detail


def test_missing_audio_or_unrenderable_slot_is_named():
    calls = {"n": 0}

    def fetch(url, headers):
        if url.endswith("/api/v1/events/hackmit-demo/readiness"):
            calls["n"] += 1
            body = readiness(calls["n"], masterAudio={"attached": False})
            body["slots"][2]["renderable"] = False
            return 200, body
        return good_backend()(url, headers)

    check = [
        c for c in pre.run_checks(CONFIG, deps(fetch)) if c.name == "compositor readiness live"
    ][0]
    assert check.status == pre.NO_GO
    assert "CAM-WIDE not renderable" in check.detail and "master audio not attached" in check.detail


def test_auto_armed_before_validation_is_no_go():
    auto = good_backend(
        {
            "/api/v1/events/hackmit-demo/control-state": (
                200,
                {
                    "mode": "AUTO",
                    "controlGeneration": "g",
                    "modeRevision": 9,
                    "pendingDecisionId": None,
                },
            )
        }
    )
    check = [c for c in pre.run_checks(CONFIG, deps(auto)) if c.name == "control state"][0]
    assert check.status == pre.NO_GO and "AUTO" in check.detail


def test_named_policy_requires_b_morning_validation_passed_today():
    named = good_backend(
        {
            "/api/v1/guests/readiness": (
                200,
                {
                    "namingPolicy": "NAMED_ASSIST",
                    "disclosure": "Names come from faces.",
                    "morningValidation": {"validatedOn": "2026-09-19", "allPassed": True},
                },
            )
        }
    )
    check = [
        c for c in pre.run_checks(CONFIG, deps(named)) if c.name == "naming policy and disclosure"
    ][0]
    assert check.status == pre.NO_GO
    validated = good_backend(
        {
            "/api/v1/guests/readiness": (
                200,
                {
                    "namingPolicy": "NAMED_ASSIST",
                    "disclosure": "Names come from faces.",
                    "morningValidation": {"validatedOn": "2026-09-20", "allPassed": True},
                },
            )
        }
    )
    check = [
        c
        for c in pre.run_checks(CONFIG, deps(validated))
        if c.name == "naming policy and disclosure"
    ][0]
    assert check.status == pre.GO and "filed today" in check.detail


def test_empty_disclosure_is_no_go_even_when_role_based():
    silent = good_backend(
        {
            "/api/v1/guests/readiness": (
                200,
                {"namingPolicy": "ROLE_BASED", "disclosure": "  ", "morningValidation": None},
            )
        }
    )
    check = [
        c for c in pre.run_checks(CONFIG, deps(silent)) if c.name == "naming policy and disclosure"
    ][0]
    assert check.status == pre.NO_GO


def test_commit_checks_tag_and_dirty_tree():
    assert pre.run_checks(CONFIG, deps(good_backend(), dirty=True))[0].status == pre.NO_GO
    assert pre.run_checks(CONFIG, deps(good_backend(), tag_sha="other"))[0].status == pre.NO_GO
    expected = pre.Config(
        **{
            **asdict(CONFIG),
            "expected_commit": "abc123d",
            "tag": None,
            "worker_python": CONFIG.worker_python,
            "recordings_dir": CONFIG.recordings_dir,
        }
    )
    assert pre.run_checks(expected, deps(good_backend()))[0].status == pre.GO


def test_offline_skips_backend_and_still_lists_physical_rows():
    offline = pre.Config(
        **{
            **asdict(CONFIG),
            "offline": True,
            "worker_python": CONFIG.worker_python,
            "recordings_dir": CONFIG.recordings_dir,
        }
    )
    checks = pre.run_checks(offline, deps(lambda url, headers: (0, "no network")))
    assert statuses(checks)["backend checks"] == pre.SKIP
    assert len([c for c in checks if c.status == pre.MANUAL]) == 6
    assert pre.verdict(checks)[0] is True
