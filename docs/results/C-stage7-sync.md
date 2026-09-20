# C-lane · Stage 7 sync report

_Written from the stage worktree on `person-c-stage-7`._

## Branch base

- New branch: `person-c-stage-7`, based on `person-c-stage-6` at
  `4255f1e`.
- My newest green C branch remains `person-c-stage-6`. No newer C
  branch appeared overnight.

## Overnight merges from A / B / D

Sourced from `git log origin/codex/stage-6-integration` and each
teammate's newest branch. Read-only — no cross-lane files touched.

| Lane | Newest overnight branch | Newest commit | What landed |
|---|---|---|---|
| A | `origin/codex/person-a-stage-6` | `52eda0c` Complete Person A Stage 6 offline handoff | Stage 6 offline handoff tooling + status |
| A (prep) | `origin/codex/person-a-stage-7-prep` | `cb9d2d5` Prepare Person A Stage 7 morning preflight | Stage 7 morning preflight scaffolding |
| B | `origin/codex/b-stage-7` | `c1ded5e` Stage 7 — demonstrate the memory-clearing restart | Restart-drill demo; two of three checks left NOT RUN |
| B (prep) | `origin/codex/b-stage-7-prep` | `7e16987` Stage 7 prep — a channel for "we re-tested this morning and it broke" | Post-rehearsal regression channel |
| D | `origin/codex/person-d-stage-6` | `7a409cc` Stage 6: record that GitHub Actions stopped starting jobs | Documented CI outage (account spending limit); trunk still green |
| Integration | `origin/codex/stage-6-integration` | `f7d760b` Integrate Stage 6 (D) | Rolls up A/B/C/D stage 6 |

Notable non-code items to know about:
- **B / Stage 7 prep** advertises a channel for regressions found the
  morning of the demo. My `morning_check.py` output should surface
  cleanly enough to paste there.
- **D / Stage 6** flagged that hosted CI stopped starting jobs. I
  will run pytest + ruff locally in step 6 rather than relying on
  GitHub Actions.
- **A / Stage 7 prep** already carries a morning-preflight scaffold.
  I will not touch A's files; my `morning_check.py` layers on top of
  `demo_preflight.py` (which is a C-owned script).

## Dry-run merge — `person-c-stage-6` → `origin/codex/stage-6-integration`

Ran without touching a real worktree:

```
git merge-tree --write-tree person-c-stage-6 origin/codex/stage-6-integration
a12064c507a62ee0b7883b67aa8f83735fe2d188
```

The merge-tree output is a single tree hash with **no** `CONFLICT`
lines — the merge is clean. Files in the reported diff between the
integration branch and my branch are all A / B / D artefacts I do
not have locally, plus the C files I own on my branch that are
already integrated at `0a49005` (Integrate Stage 6 (C)).

Nothing to resolve. When A opens the Stage-7 integration branch, my
`person-c-stage-7` should also merge cleanly on top; I will re-run
this check before pushing.

## Do-not-touch confirmation

- No A files (`apps/api/src/cue_api/{contracts,livekit_tokens,main,
  settings}.py`, `apps/web/`, `packages/contracts/`) modified on
  `person-c-stage-7`.
- No B files (`apps/api/src/cue_api/identity/`, `apps/api/src/cue_api/
  media/`, B's Stage docs) modified.
- No D files (`scripts/verify_recording.py`, `scripts/av_skew.py`,
  `scripts/mac_config_snapshot.py`, `scripts/b_offline_regression.py`,
  D's Stage docs) modified.

The Stage 7 change set is confined to:
- `scripts/morning_check.py`, `scripts/fallback_drill.py` (new)
- `config/demo.example.env`, `config/demo_roster.json` (new)
- `apps/api/src/cue_api/config/demo_profile.py` (new, opt-in via
  `CUE_PROFILE=demo`; does not alter default behaviour)
- `apps/api/tests/test_demo_profile.py`, associated fixtures (new)
- `docs/results/C-stage7-*.md`, `docs/PITCH-numbers.md` (new)
- One-line fix to `docs/results/C-soak.md` to align with what the
  overnight handoff already says.
