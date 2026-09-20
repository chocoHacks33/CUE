# Person A Stage 6 handoff

Branch: `codex/person-a-stage-6`

A's Stage 6 work is complete on the integrated Stage 5 tree. Stage 6 is not a
feature stage: the only permitted work is a bounded offline regression, an
accurate handoff and then stopping until the physical system can be
re-established. No media architecture, model migration, deployment or release
tag was added.

## A completed

- Integrated the offline handoff tool after all four Stage 5 lanes.
- Pinned every report to an exact commit and branch.
- Bounded the offline suite to ten minutes by default.
- Removed OpenAI, Deepgram, LiveKit and CUE production credentials from child
  test processes.
- Ran only existing tests, lint, type-check and production build—no installs,
  provider requests, deployment, tag or push operation.
- Required concrete blockers, completed work, morning actions, venue-rule
  acknowledgement and an explicit owner-to-owner transfer.
- Made it impossible for an offline PASS to claim hardware validation or release
  certification.

## Current outgoing handoff

- From: A
- Intended recipient: D
- Release mode: `ROLE_BASED_ASSIST`
- Hardware status: `NEEDS_REVALIDATION`
- Release status: blocked; there is no passing A release tag
- D acknowledgement: **PENDING**

Known blockers inherited from the integrated records:

1. No three-camera live feed has reached D's Mac.
2. A/B/C/D physical Stage 4 gates are not run.
3. D's recording, playback, backup, A/V and soak checks are not run.
4. The saved Plume project has not been reopened and verified.
5. Named AUTO is unsupported; keep the role-based ASSIST disclosure.
6. The integrated API suite is red on A's Windows FFmpeg 8.0.1 host: 687
   tests pass, 3 skip and 3 recording-verifier tests fail because FFmpeg emits
   `Error parsing Opus packet header` for its own synthetic WebM. The same
   suite passed on D's Mac at Stage 5. Re-run it on D's exact environment;
   do not suppress a decoder error merely to make the check green.

Because D has not acknowledged this handoff, the private handoff JSON must keep
`handoffAgreed` false and the generated report remains INCOMPLETE. That is an
accurate owner-transfer state, not a software failure.

## D acceptance

After reviewing this branch, D copies the template to the ignored handoff file,
sets its `commit` to the exact integrated candidate, confirms the blockers and
morning actions, then changes `handoffAgreed` to true:

```bash
cd apps/api
python -m pip install -e ".[dev]"
cue-offline-handoff --run-suite --maximum-seconds 600
```

The private `artifacts/stage6-offline-report.json` should then say PASS while
still stating `hardwareValidated: false` and `releaseCertified: false`.

## Verification on A's Windows laptop

| Check | Result |
|---|---|
| Stage 6 unit tests | PASS — 7 passed |
| API lint | PASS |
| Contracts tests | PASS — 53 passed |
| Web tests | PASS — 154 passed |
| Type-check | PASS |
| Production build | PASS |
| Full API suite | FAIL — 687 passed, 3 skipped, 3 FFmpeg recording-verifier failures |

The failed full-suite row is intentionally carried into the handoff. It is not
evidence of a physical recording failure, but it also cannot be called PASS
without a clean decoder run on D's Mac.

## Stage 7 restart order

1. Check current organizer/venue announcements and assigned location.
2. Confirm the exact clean, pushed candidate and private configuration on D's
   Mac; do not upgrade dependencies.
3. Reconnect and physically identify all three Windows camera laptops.
4. Revalidate framing, A-only master audio, identity state and real speech.
5. Run the recording/playback and soak gates before reconsidering release.
6. Keep `ROLE_BASED_ASSIST` and disclose limitations if any gate is incomplete.
