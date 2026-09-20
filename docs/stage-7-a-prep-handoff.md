# Person A Stage 7 preliminary handoff (superseded)

The integrated A handoff is in
[`stage-7-a-handoff.md`](stage-7-a-handoff.md). This file remains as the
dependency-free preparation record.

Branch: `codex/person-a-stage-7-prep`

This branch starts from `codex/stage-5-integration` and has no Stage 6 code
dependency. It prepares A's Sunday-morning validation path without claiming
that the venue, network or four-laptop setup has already been tested.

## Prepared now

- `cue-stage7-preflight` binds the run to the exact clean, pushed commit.
- The private evidence requires the current assigned judging location, a
  timezone-aware announcement check, power access, all chargers and a cable
  safety plan.
- Live probes verify API liveness/readiness, the exact three-camera topology,
  rejection without admission auth and successful subscribe-only receiver
  admission with the real secret kept only in `.env`.
- A second valid admission must receive a fresh receiver identity for the same
  room. This proves credential reissue, not a complete browser/media reconnect.
- A's physical CAM-HOST reconnect must be observed and must return to ASSIST.
- Stage 6's handoff must be reviewed before A can pass, even though this code can
  be developed and merged independently.
- The report always leaves `systemValidated`, `hardwareValidated` and
  `releaseCertified` false. B, C and D retain their physical gates.

## Use after Stage 6 integration

1. Copy `docs/results/stage7-a-preflight.template.json` to the ignored
   `docs/results/stage7-a-preflight.json`.
2. On D's Mac, confirm the exact release candidate and start the existing API.
3. On A's Windows laptop, use the current private `.env`, fill the venue and
   reconnect evidence, then run:

   ```bash
   cd apps/api
   python -m pip install -e ".[dev]"
   cue-stage7-preflight --run-live
   ```

4. Keep `artifacts/stage7-a-preflight-report.json` and supporting evidence
   private. Do not commit keys, receiver tokens, location screenshots or logs.
5. A may report complete only when the report says PASS on the exact candidate.

## Still physical and unverified

- Current organizer announcement, judging location and power availability.
- Venue reachability from A's actual laptop and current network.
- CAM-HOST framing, master microphone and real browser reconnect.
- B/C identity and speech-position checks.
- D's mappings, A audio, clap/flash timing, soak and recording playback.
- Any change made after the preflight commit.

If any capability fails, keep the release in role-based ASSIST, disable or
disclose the failed capability, and update the saved submission before judging.

## Preliminary verification on A's Windows laptop

| Check | Result |
|---|---|
| Stage 7 focused tests | PASS — 7 passed |
| API lint | PASS |
| Contracts tests | PASS — 53 passed |
| Web tests | PASS — 154 passed |
| Type-check | PASS |
| Production build | PASS |
| Full API suite | 687 passed, 3 skipped, 3 existing FFmpeg 8 verifier failures |
| Live venue/API probe | NOT RUN — requires current Stage 7 setup |

The three full-suite failures are the existing Windows FFmpeg 8.0.1 synthetic
WebM `Error parsing Opus packet header` results. The focused Stage 7 code does
not alter or suppress the recording verifier. D must rerun the complete suite
in the final Mac environment.
