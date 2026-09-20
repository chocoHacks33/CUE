# Person A Stage 5 preliminary handoff

Branch: `codex/person-a-stage-5-prep`

This branch starts from the shared Stage 3 integration and has no dependency on
Stage 4 code. It prepares the release mechanism; it does not claim that Stage 4
passed and it does not create a release tag.

## Prepared now

- `cue-release-preflight` creates a no-secrets manifest for the exact commit.
- Release readiness fails closed unless the tree is clean, HEAD is pushed,
  supported Python/Node versions and lock/source files are present, `.env` is
  complete, the full suite passes, providers authenticate and a fresh API
  process reaches readiness.
- The approval file is bound to the exact tested commit and requires PASS from
  A/B/C/D Stage 4 gates, D's Mac checks, saved-and-reopened submission checks,
  limitations review and all four owner sign-offs.
- The tool never creates or pushes a Git tag. A reviews the generated manifest
  and tags the exact commit manually only after it says `releaseReady: true`.
- A private runbook template covers topology, clean startup, degraded recovery,
  shutdown and submission persistence without committing secrets.

## Integration after Stage 4

1. Integrate all accepted Stage 4 branches and run any affected physical tests.
2. Copy `docs/results/stage5-release-approval.template.json` to
   `docs/results/stage5-release-approval.json` and fill it using real evidence.
3. Copy the runbook template outside the public repository and fill it on D's
   Mac. Keep secrets and private recordings out of Git.
4. Commit and push the exact candidate, then run on D's Mac:

   ```bash
   cd apps/api
   python -m pip install -e ".[dev]"
   cue-release-preflight --run-suite --startup-smoke --provider-smoke
   ```

5. Read `artifacts/stage5-release-manifest.json`. Any FAIL or INCOMPLETE means
   no release tag and no AUTO claim.
6. Only after PASS, manually create an annotated tag on the manifest's exact
   commit and push that tag. Reopen the saved submission and verify persistence.

## What still requires the integrated system

- All four Stage 4 reports and sign-offs.
- Three real feeds, recording playback and clean startup on D's Mac.
- Live OpenAI/Deepgram credential checks.
- Final saved Plume fields, members and actual track selection.
- The annotated release tag itself.
