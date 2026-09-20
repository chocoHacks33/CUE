# Person A Stage 5 handoff

Branch: `codex/person-a-stage-5`

Person A's Stage 5 release implementation is complete on the integrated Stage 4
tree. The current candidate is deliberately **not tagged** because the Stage 4
integration record says every physical row is NOT RUN and no live camera has
reached D's Mac. The saved Plume project has also not been supplied for A to
reopen and verify. Creating a passing tag in that state would be false evidence.

## Completed implementation

- `cue-release-preflight` binds the release to an exact clean, pushed commit.
- It runs the backend and web suites, lint, type-check and production build.
- It starts a fresh API process and checks readiness, the three-camera topology,
  A's Stage 4 report route and B's readiness route.
- It verifies that the built web index references present production assets.
- It checks live OpenAI and Deepgram authentication without printing keys.
- It refuses tracked `.env`, model weights, recordings and runtime artifacts.
- The approval is private/ignored and requires A/B/C/D Stage 4 decisions,
  evidence references, the declared release mode, D's Mac checks, limitations
  review, all four sign-offs, and saved/reopened submission evidence.
- `cue-release-finalize` revalidates the PASS manifest and approval against HEAD,
  clean state, pushed state and tag uniqueness. It performs no mutation unless
  `--create-tag` is explicitly supplied and pushes only with `--push`.

## Honest release mode

The integrated Stage 4 decision is `ROLE_BASED_ASSIST`: camera roles are used,
no person is named from face recognition, and the producer confirms suggestions.
Do not change the approval to `NAMED_AUTO` unless new measured evidence changes
the Stage 4 decision.

## Exact completion sequence on D's Mac

1. Run and retain the real Stage 4 checks for A, B, C and D on the candidate.
2. Fill the ignored `docs/results/stage5-release-approval.json` from the template.
3. Fill and execute the private release runbook.
4. Save the Plume project, reopen it, verify all four members/fields/track and
   record the safe evidence reference and timestamp in the approval.
5. Commit and push the exact candidate. Run:

   ```bash
   cd apps/api
   python -m pip install -e ".[dev]"
   cue-release-preflight --run-suite --startup-smoke --provider-smoke
   cue-release-finalize
   ```

6. Review the manifest. Only if both commands pass:

   ```bash
   cue-release-finalize --create-tag --push
   ```

The finalizer cannot turn an INCOMPLETE/FAIL manifest into a release and does
not infer a physical test from an automated test.
