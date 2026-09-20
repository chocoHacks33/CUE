# Person A Stage 7 handoff

Branch: `codex/person-a-stage-7`

A's Stage 7 software work is complete. This branch starts from the current
remote default integration branch, merges A's Stage 7 preparation and carries
A's Stage 6 work forward. It provides a fail-closed morning gate; it does not
invent venue or hardware evidence.

## A completed

- Bound the morning run to the exact clean, pushed commit.
- Required the current assigned judging location, organizer-check time, private
  evidence reference, confirmed power, all chargers and a cable-safety plan.
- Added live API liveness/readiness and exact three-camera topology probes.
- Proved the admission endpoint rejects a missing secret and can issue a
  subscribe-only director session without logging the secret or token.
- Required a second admission to receive a new receiver identity in the same
  room. This checks credential reissue but does not claim a media reconnect.
- Required a real CAM-HOST reconnect and evidence that the system returns to
  ASSIST rather than silently resuming AUTO.
- Required review of the Stage 6 handoff and an explicit limitations update.
- Kept the evidence and generated report private and ignored by Git.
- Kept `systemValidated`, `hardwareValidated` and `releaseCertified` false even
  when Person A's own preflight passes.

## Current status

A's implementation and automated verification are complete. The operational
morning gate remains **INCOMPLETE** because this checkout has no private `.env`,
`docs/results/stage6-handoff.json` or
`docs/results/stage7-a-preflight.json`. Therefore none of these are claimed:

1. current judging location or organizer announcement checked;
2. power/outlet and cable placement checked;
3. A-to-Mac venue network/auth path checked;
4. physical CAM-HOST reconnect and return-to-ASSIST observed;
5. exact live candidate accepted by D.

## Integration truth

At the time this branch was created, GitHub's default integration branch
contained B's Stage 6 work but did not contain the remote A, C or D Stage 6
heads. This branch explicitly carries A's Stage 6 head. C and D remain outside
this A-owned branch and must be present in D's final integration candidate.

## Run A's real morning gate

1. D checks out the final integrated candidate and starts the existing API.
2. Copy `docs/results/stage7-a-preflight.template.json` to the ignored
   `docs/results/stage7-a-preflight.json`.
3. A verifies the current location/power and physically reconnects CAM-HOST.
4. Fill only observed evidence. Keep `ROLE_BASED_ASSIST` unless the complete
   current evidence supports a narrower claim.
5. From `apps/api` on A's Windows laptop:

   ```bash
   python -m pip install -e ".[dev]"
   cue-stage7-preflight --run-live
   ```

6. Preserve `artifacts/stage7-a-preflight-report.json` privately. A is ready
   only when it says PASS on the same commit D is running.

Any new commit, URL, room/event, moved laptop or changed venue condition
invalidates the relevant evidence and requires a rerun.

## Automated verification on A's Windows laptop

| Check | Result |
|---|---|
| Stage 7 focused tests | PASS — 7 passed |
| B Stage 7 compatibility tests | PASS — 48 passed |
| API lint | PASS |
| Contracts tests | PASS — 53 passed |
| Web tests | PASS — 154 passed |
| Type-check | PASS |
| Production build | PASS |
| Full API suite | 715 passed, 3 skipped, 3 existing FFmpeg 8 verifier failures |

The three failures are the already recorded Windows FFmpeg 8.0.1 synthetic
WebM `Error parsing Opus packet header` results. The recording verifier was not
weakened. D must rerun the suite on the final Mac candidate.

## Handoff to D

D must combine this branch with the missing C/D Stage 6 integration, review the
private A report, then run D's mappings, master-audio, clap/flash, soak and
recording-playback gates. A's PASS can never substitute for those checks.
