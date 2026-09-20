# Person A Stage 4 handoff

Branch: `codex/person-a-stage-4`

Person A's failure, access and release-gate implementation is complete. The
gate is intentionally fail-closed: it cannot say that A is ready for AUTO until
D records the required physical trials on the integrated system. Passing A's
gate is necessary but does not replace B's identity gate, C's semantic gate or
D's recording/soak gate.

## What is implemented

- Reconnects remain bound to the server-owned `CAM-HOST`, `CAM-GUEST` and
  `CAM-WIDE` slots; republishing advances the stream epoch and late detaches do
  not remove the current track.
- Invalid, expired and cross-event control sessions are rejected, and observer
  attempts to mutate renderer/readiness state are refused.
- A failed Deepgram send produces one immediate speech-down transition. A
  provider is marked recovered only after a real provider message arrives.
- `Stage4EvidenceStore` keeps evidence isolated by event, accepts identical
  retries idempotently and rejects a reused trial ID with different evidence.
- New evidence cannot be added after an event ends, but the final report stays
  available for export and judging evidence.
- A live source-loss row must include a measured latency. Replay or automated
  evidence cannot satisfy a requirement marked LIVE.
- The gate reports `PASS`, `FAIL` or `INCOMPLETE`; only `PASS` makes
  `autoEligible` true for A's gate.

## Evidence API

Both endpoints require `X-CUE-Producer-Secret` and are therefore operated from
D's Mac, not from publisher laptops.

```text
POST /api/v1/events/{eventId}/stage4/trials
GET  /api/v1/events/{eventId}/stage4/report
```

Example trial submission:

```bash
curl -X POST "http://localhost:8000/api/v1/events/hackmit-demo/stage4/trials" \
  -H "Content-Type: application/json" \
  -H "X-CUE-Producer-Secret: $CUE_PRODUCER_SECRET" \
  -d '{
    "trialId": "loss-01",
    "area": "SOURCE_LOSS",
    "passed": true,
    "evidenceKind": "LIVE",
    "latencyMs": 1080,
    "detail": "CAM-GUEST blocked while live; first safe CAM-WIDE frame rendered"
  }'
```

Retrieve the current report:

```bash
curl "http://localhost:8000/api/v1/events/hackmit-demo/stage4/report" \
  -H "X-CUE-Producer-Secret: $CUE_PRODUCER_SECRET"
```

The exact physical actions and trial IDs are in
[`results/a-stage4-failure-check.md`](results/a-stage4-failure-check.md). The
file-based fallback remains available:

```bash
cd apps/api
cue-stage4-gate ../../docs/results/a-stage4-failure-report.json
```

## A's exit conditions

| Area | Required evidence |
|---|---|
| Routing/reconnect | 20 LIVE trials, zero failures |
| Source loss | 10 LIVE trials, every latency present, p95 at most 1,500 ms |
| Backend failure | 1 LIVE pass |
| Speech-provider failure | 1 LIVE pass |
| Semantic-provider failure | 1 LIVE pass |
| Event access | 1 AUTOMATED-or-better pass |
| Observer/control | 3 AUTOMATED-or-better passes |

Until D completes those trials, the accurate status is: **A's Stage 4 code is
complete; A's physical operational gate is INCOMPLETE, so AUTO is not yet
authorised.**

## Verification

From the repository root:

```bash
cd apps/api
python -m pytest
python -m ruff check src tests

cd ../..
npm test
npm run typecheck
npm run build
```
