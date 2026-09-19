# Person A Stage 0 handoff

## Completed in this branch

- Repository, app boundaries and cross-platform setup instructions.
- Shared IDs and audio policy for `CAM-HOST`, `CAM-GUEST` and `CAM-WIDE`.
- FastAPI health/topology endpoints and a guarded LiveKit token endpoint.
- React publisher with explicit local preview, publish/stop controls and visible state.
- `CAM-HOST` publishes camera plus the master mic; the other two IDs publish video only.
- Automated API, contract and browser-policy tests.

## A + D physical exit test

This cannot be truthfully completed without D's MacBook and real LiveKit credentials.

1. D checks out this exact branch and configures `.env` locally on the Mac.
2. D starts the API and web app and confirms `/health/live` and `/health/ready`.
3. A opens the HTTPS publisher from the Windows laptop and selects `CAM-HOST`.
4. A starts the local preview, says a distinctive marker and waves on camera.
5. A publishes. D subscribes using a LiveKit room inspector or D's Stage 0 receiver skeleton.
6. Both verify the remote video is A's physical webcam, the participant metadata says `CAM-HOST`, and exactly one audio track comes from A.
7. Stop and republish once. Record the new LiveKit track SID; do not treat a SID as the stable camera ID.
8. Save the result in `docs/results/a-d-stage-0-media-check.md` without secrets or raw private recordings.

Stage 0's shared exit gate is open only after the Mac dependency install and this real remote feed pass. A's code being green on Windows is necessary, not sufficient.
