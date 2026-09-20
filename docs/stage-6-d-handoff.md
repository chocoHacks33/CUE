# Person D Stage 6 handoff: overnight, no code

Branch `codex/person-d-stage-6`, docs only, on the frozen trunk 296e112. Date: 2026-09-19 (Boston).

Stage 6 in the v3 plan is the overnight window: a short handoff and offline regression checks, then rest. No new media architecture, no model migration, no major feature, and hardware-dependent fixes stay unverified until the venue reopens. This branch follows that: nothing in `apps/`, `packages/` or `scripts/` changed. The record of what was run is `docs/results/d-stage-6-check.md`.

## What was established tonight

- The exact frozen commit passes every offline check A's release preflight can make on this Mac: suites, lint, type-check, production build, a fresh API start reaching ready with three cameras, and no private artifacts tracked.
- B's models load and infer on this Mac through B's own tests, with weights verified against B's pins. The whole API suite runs here with no skips (703 passed).
- The release is correctly **not** ready: the approval file does not exist, the provider smoke has not run, and the three provider variables in the root `.env` are empty.

## The one thing that blocks Sunday before any camera does

`OPENAI_API_KEY`, `DEEPGRAM_API_KEY` and `CUE_MODEL` are empty in the root `.env` on the Mac. Nothing overnight can fix that; only the person holding the keys can. It should be the first action after 08:00, before the tunnel and before the publishers connect, because C's live lane and A's provider smoke both stop without them.

## What D will not do overnight

- No dependency upgrades, no package installs, no changes to the Mac's Python or Node.
- No camera or network tests at the closed venue.
- No retuning of the failover constants (the Stage 4 handoff, section 5, says decide after ten real trials).

## Morning sequence

`docs/results/d-stage-6-check.md`, section 5, and the runbook sections "Sunday morning: re-establish" and "Stage 5: freeze, capture, backup" in `docs/stage-0-d-mac-run.md`.

## For A

A's `cue-offline-handoff` (Stage 6 prep branch, not yet on trunk) wants a private handoff JSON agreed by two named owners. D's side of that agreement is this page: blockers are the empty provider keys and every unrun physical row; completed offline work is section 1 to 3 of the check; morning-first is section 5. When A's branch lands, D fills the JSON from here.
