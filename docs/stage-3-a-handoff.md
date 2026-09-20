# Person A Stage 3 handoff

Branch: `codex/person-a-stage-3`

Person A's Stage 3 implementation is complete in code. This branch starts from
the shared Stage 2 integration, includes B's Stage 3 measurement prep, merges
D's Stage 3 renderer/control UI, and connects A's recovery APIs to D's real
LiveKit receiver callbacks. The physical Stage 3 exit gate remains deliberately
unclaimed until D runs the three Windows publishers and master microphone on
the MacBook.

## A's completed work

- Replaced the receiver's local transport assumptions with authenticated
  `video-attached` and `video-detached` calls from actual LiveKit callbacks.
- Serializes mutations per camera, so rapid publish/unpublish callbacks cannot
  reach the backend out of order. Different cameras remain independent.
- Fetches the complete authoritative binding snapshot before joining and after
  every LiveKit reconnect. Participants without the backend-approved identity
  are never displayed or subscribed.
- Uses backend-owned stream epochs. Direct replacement and clean
  detach/reconnect both advance the epoch; stale participant metadata cannot
  rewind it.
- Ignores late detach events for replaced tracks and prevents duplicate-slot
  identities from clearing or taking over the approved source.
- Invalidates visual identity evidence on detach/republish, so B's observations
  cannot cross a physical-stream boundary.
- On compositor reconnect, an exact report of the picture actually on air now
  cancels any unreachable pending command, records it as rejected, advances the
  revision and rejects its late ACK.
- Added an explicit operator event-end action. It reports final detaches,
  disconnects the LiveKit receiver, ends control, revokes sessions, deletes
  pairing/binding state and event-scoped identity references, then fences the
  event ID for the rest of the API process.
- Preserves `CAM-HOST` as the only audio source throughout video cuts and
  reconnects.

## Fail-closed rules

1. Stage 3 connection requires both the receiver/bootstrap credential and the
   producer credential held on D's Mac.
2. Server metadata identifies the requested camera, but the current backend
   binding decides whether that participant owns it.
3. A video is attached to a tile only after the backend accepts its exact
   participant identity and track SID.
4. A transport API failure unsubscribes the video instead of displaying an
   unverified source.
5. AUTO commands still require D's first-frame `APPLIED` ACK. Reconciliation
   reports the actual canvas; it never pretends a requested cut was rendered.

## Automated verification

From the repository root:

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

From `apps/api`:

```powershell
python -m pip install -e ".[opencv,dev]"
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest
python -m pytest tests/test_worker_ingest.py
```

Install the `opencv` extra on D's Mac before the physical gate. Without it, the
OpenCV adapter tests are intentionally skipped and the real vision path is not
ready for a live rehearsal.

The tests cover direct replacement, clean reconnect, late callback ordering,
duplicate ownership, snapshot reconciliation, event cleanup, pending-command
reconciliation and D's real control-message shapes. They are automated
protocol tests, not evidence that physical cameras were used.

Final results on A's Windows machine for this branch:

- contracts: 43 passed;
- web: 123 passed;
- API virtual environment: 447 passed, 2 skipped;
- worker ingest under the system Python environment: 4 passed;
- typecheck, Ruff and the production web build: passed.

The two virtual-environment skips are the optional OpenCV adapter suite and the
NumPy-dependent worker case. The worker case passed in the system environment;
the OpenCV extra still has to be installed and exercised on D's live Mac setup.

## Required live gate with D

Run every row in `docs/results/a-stage3-integration-check.md` at the exact
commit being considered for release. The required timeline is:

1. future mention — no cut;
2. unscripted immediate introduction — verified named take;
3. cover or stall that camera — safe fallback or slate;
4. manual HOLD while an automatic command is late — HOLD wins;
5. disconnect/rejoin one publisher — same camera ID, new epoch, no identity
   carried across the reconnect;
6. play the resulting programme recording independently with continuous A
   audio.

Until that is recorded as PASS, report: “Person A Stage 3 code complete; live
Stage 3 system gate not yet run.”
