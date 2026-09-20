from __future__ import annotations

from fastapi.testclient import TestClient

from cue_api.main import create_app
from cue_api.settings import Settings

PRODUCER = {"X-CUE-Producer-Secret": "producer-secret"}


def client() -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                _env_file=None,
                cue_producer_secret="producer-secret",
            )
        )
    )


def trial(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "trialId": "route-01",
        "area": "ROUTING_RECONNECT",
        "passed": True,
        "evidenceKind": "LIVE",
        "latencyMs": None,
        "detail": "CAM-HOST rejoined the same fixed slot",
    }
    value.update(overrides)
    return value


def test_stage4_evidence_requires_the_producer_credential() -> None:
    test_client = client()
    posted = test_client.post("/api/v1/events/demo/stage4/trials", json=trial())
    report = test_client.get("/api/v1/events/demo/stage4/report")
    assert posted.status_code == 401
    assert report.status_code == 401


def test_trial_retries_are_idempotent_but_conflicting_reuse_is_refused() -> None:
    test_client = client()
    path = "/api/v1/events/demo/stage4/trials"
    first = test_client.post(path, headers=PRODUCER, json=trial())
    replay = test_client.post(path, headers=PRODUCER, json=trial())
    conflict = test_client.post(
        path,
        headers=PRODUCER,
        json=trial(detail="different physical result"),
    )

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert replay.status_code == 201
    assert replay.json()["created"] is False
    assert len(replay.json()["report"]["trials"]) == 1
    assert conflict.status_code == 409


def test_reports_are_event_scoped_and_fail_closed() -> None:
    test_client = client()
    response = test_client.post(
        "/api/v1/events/demo-a/stage4/trials",
        headers=PRODUCER,
        json=trial(),
    )
    assert response.status_code == 201

    first = test_client.get("/api/v1/events/demo-a/stage4/report", headers=PRODUCER)
    other = test_client.get("/api/v1/events/demo-b/stage4/report", headers=PRODUCER)
    assert len(first.json()["trials"]) == 1
    assert first.json()["assessment"]["status"] == "INCOMPLETE"
    assert first.json()["assessment"]["autoEligible"] is False
    assert other.json()["trials"] == []


def test_live_source_loss_requires_a_measured_latency() -> None:
    test_client = client()
    response = test_client.post(
        "/api/v1/events/demo/stage4/trials",
        headers=PRODUCER,
        json=trial(
            trialId="loss-01",
            area="SOURCE_LOSS",
            detail="CAM-HOST loss rendered the safe wide source",
        ),
    )
    assert response.status_code == 422


def test_event_end_fences_new_trials_but_retains_the_report() -> None:
    test_client = client()
    path = "/api/v1/events/demo/stage4/trials"
    assert test_client.post(path, headers=PRODUCER, json=trial()).status_code == 201
    assert test_client.post("/api/v1/events/demo/end", headers=PRODUCER).status_code == 200

    late = test_client.post(
        path,
        headers=PRODUCER,
        json=trial(trialId="route-02"),
    )
    report = test_client.get("/api/v1/events/demo/stage4/report", headers=PRODUCER)
    assert late.status_code == 410
    assert [item["trialId"] for item in report.json()["trials"]] == ["route-01"]
