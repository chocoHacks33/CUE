from __future__ import annotations

import json
from dataclasses import asdict

from cue_api.contracts import CameraId
from cue_api.control import ControlStore
from cue_api.control_contracts import ControlMode
from cue_api.integration_fixture import MockCompositor, Stage2FixtureRunner
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent


def main() -> None:
    """Run the fixture-only cue-to-ACK loop and print its evidence as JSON."""
    event_id = "fixture-stage2"
    store = ControlStore()
    runner = Stage2FixtureRunner(
        event_id=event_id,
        store=store,
        compositor=MockCompositor({CameraId.HOST: 2, CameraId.GUEST: 3, CameraId.WIDE: 1}),
        current_camera=CameraId.HOST,
        current_stream_epoch=2,
    )
    store.set_mode(
        event_id,
        mode=ControlMode.AUTO,
        expected_revision=0,
        idempotency_key="fixture-enable-auto",
    )
    result = runner.run(
        cue=Cue(
            target_guest_ids=["sarah"],
            scope=Scope.SINGLE,
            intent=Intent.INTRODUCE,
            temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW,
            evidence_text="Sarah, please join us now",
            utterance_id="fixture-utterance-1",
            created_at=10.0,
        ),
        cameras={
            "CAM-HOST": {"role": "host", "healthy": True, "epoch": 2},
            "CAM-GUEST": {
                "role": "guest",
                "healthy": True,
                "epoch": 3,
                "confirmed_guest_ids": ["sarah"],
                "evidence_age_s": 0.2,
            },
            "CAM-WIDE": {"role": "wide", "healthy": True, "epoch": 1},
        },
        decision_key="fixture-decision-1",
        now_s=10.0,
    )
    print(
        json.dumps(
            {
                "fixtureOnly": True,
                "decision": asdict(result.decision),
                "command": (
                    result.command.model_dump(mode="json", by_alias=True)
                    if result.command
                    else None
                ),
                "acknowledgement": (
                    result.acknowledgement.model_dump(mode="json", by_alias=True)
                    if result.acknowledgement
                    else None
                ),
                "state": result.state.model_dump(mode="json", by_alias=True),
                "metrics": store.latency_metrics(event_id).model_dump(mode="json", by_alias=True),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
