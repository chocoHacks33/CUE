# Person A Stage 4 preliminary handoff

Branch: `codex/person-a-stage-4-prep`

This branch starts from the shared Stage 3 base before A's Stage 3 integration.
It deliberately does not import A's Stage 3 transport implementation. Its files
are a forward-compatible failure gate and hardening at existing provider/control
boundaries, so it can be merged after Stage 3 without being needed by Stage 3.

## Prepared now

- `stage4_gate.py` makes A's Stage 4 acceptance evidence executable:
  20 live routing/reconnect trials with zero failures, 10 live source-loss
  trials with p95 at or below 1.5 seconds, live backend and provider failures,
  event isolation and all three observer mutation refusals.
- Replay and automated evidence cannot satisfy requirements marked LIVE.
- `cue-stage4-gate` reads the saved JSON report, prints every missing/failing
  area and exits non-zero until the operational evidence is complete.
- A failed Deepgram send now produces one immediate speech-down event instead
  of escaping into the media loop. Recovery is announced only after a real
  provider message arrives.
- Invalid, expired and cross-event control sessions now return a structured
  control error before the socket closes. D's existing client can therefore
  request a fresh short-lived session instead of retrying a dead token forever.
- The control-session clock is injectable, so expiry is tested without sleeps.

## Merge boundary after Stage 3

1. Merge A's completed Stage 3 branch first.
2. Merge this branch and resolve only overlapping imports/session-store edits;
   keep Stage 3's event cleanup and transport reconciliation.
3. Run the full Python and web suites.
4. D runs `docs/results/a-stage4-failure-check.md` on the integrated commit.
5. Save the completed JSON report and its real recordings/logs.

This preliminary branch does **not** add synthetic transport callbacks or claim
that source failover was physically measured. Stage 3 supplies the real attach,
detach and cleanup path; Stage 4 tests it under failure.

## Automated checks

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests

cd ..\..
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

Results on A's Windows machine for this branch:

- API virtual environment: 496 passed, 2 optional-dependency skips;
- worker ingest under system Python: 4 passed;
- web: 114 passed;
- shared contracts: 43 passed;
- Ruff, typecheck and the production web build: passed.

The skipped cases require the optional OpenCV and NumPy packages. They do not
count as live Stage 4 evidence; D must install the full runtime before the gate.

Until the physical report passes, say: “A's Stage 4 preliminaries are complete;
the operational failure gate has not been run on the integrated live system.”
