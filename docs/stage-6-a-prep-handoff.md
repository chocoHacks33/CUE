# Person A Stage 6 preliminary handoff (superseded)

The integrated Stage 6 handoff is in
[`stage-6-a-handoff.md`](stage-6-a-handoff.md). This file remains as the
pre-Stage-5 integration record.

Branch: `codex/person-a-stage-6-prep`

This branch starts from the Stage 4 integration and has no Stage 5 dependency.
It prepares only the bounded offline handoff permitted in Stage 6. It adds no
media architecture, model migration, provider call, deployment or release tag.

## Prepared now

- `cue-offline-handoff` runs the existing backend/web tests, lint, type-check
  and build from installed dependencies with a configurable hard time budget.
- Provider and LiveKit credentials are removed from every child test process;
  the command list contains no install, provider, deploy or Git mutation step.
- The private handoff is bound to the exact commit and two named owners.
- It requires concrete blockers, completed offline work and morning-first
  actions, plus acknowledgement of venue rules and the feature freeze.
- `hardwareStatus` must remain `NEEDS_REVALIDATION`; the generated report always
  says `hardwareValidated: false` and `releaseCertified: false`, even on PASS.
- Secret-like fields are refused. The real handoff and generated report are
  ignored private artifacts; only the blank handoff template is committed.

## Use after Stage 5 integration

1. Copy `docs/results/stage6-handoff.template.json` to the ignored
   `docs/results/stage6-handoff.json`.
2. Fill the exact commit, agreed A-D owner transfer, blockers, work completed and
   the real post-reopening resume time. Both people agree before setting
   `handoffAgreed` to true.
3. From `apps/api`, run:

   ```bash
   python -m pip install -e ".[dev]"
   cue-offline-handoff --run-suite --maximum-seconds 600
   ```

4. Preserve `artifacts/stage6-offline-report.json` privately. PASS means only
   that offline regression and the handoff passed.
5. Stop work. Do not attempt unavailable venue camera checks overnight.

## Morning boundary

Stage 7 must still re-establish network/auth, cameras, framing, identity state,
speech, output recording and the exact release commit on D's Mac. Any overnight
hardware-related code change remains unverified until that run.
