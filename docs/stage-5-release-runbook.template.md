# CUE release runbook — private working copy template

Copy this file outside the public repository, fill it in on D's Mac and keep it
with the release evidence. Do not add secrets, biometric references or private
recordings to Git.

## Exact build

- Commit: `FILL_IN_FULL_SHA`
- Release tag after preflight PASS: `cue-hackmit-2026-demo`
- D's tested Mac and OS: `FILL_IN`
- Node/Python versions: `FILL_IN`
- Public HTTPS endpoint: `FILL_IN`
- LiveKit region: `FILL_IN`

## Source map

| Physical machine | Fixed source | Audio |
|---|---|---|
| A Windows laptop | `CAM-HOST` | only programme microphone |
| B Windows laptop | `CAM-GUEST` | disabled |
| C Windows laptop | `CAM-WIDE` | disabled |
| D MacBook | central backend/director/recorder | subscribes only |

## Clean startup

1. Start from the exact clean commit above; do not upgrade dependencies.
2. Copy the previously verified private `.env` into the repository root.
3. Create/activate the Python 3.11+ environment and install `apps/api[dev]`.
4. Run `npm ci` from the repository root.
5. Run `cue-release-preflight --run-suite --startup-smoke --provider-smoke`.
6. Do not continue unless its manifest is `PASS` and names the same commit.
7. Start the API on D's Mac, then the web UI and approved HTTPS tunnel.
8. Pair A, B and C to their physically labelled slots and verify A-only audio.
9. Open the producer view, verify all three decoded feeds and start recording.

## Degraded recovery

- Control/backend loss: keep current media, use local MANUAL and show DEGRADED.
- Camera loss: take an approved healthy source or slate; never guess a slot.
- Speech/semantic provider loss: HOLD; continue manual switching.
- Wrong/uncertain identity: use operator-confirmed or role-based ASSIST.
- Recording warning: stop claims of recorded output until a new file plays back.

## Shutdown

1. End the event so sessions and consented in-memory identity state are purged.
2. Stop publishers, producer UI, API and tunnel.
3. Play the official recording independently and record its safe evidence link.
4. Confirm `.env`, recordings, biometrics, logs and `artifacts/` are not tracked.

## Submission verification

- All four members visible and verified.
- Actual track name and sponsor selections confirmed.
- Repository/release link opens without private credentials.
- Claims match measured Stage 4 evidence and disclosed fallback mode.
- Saved project reopened and every field persisted.
- Demo video/official recording plays from the submitted link.
