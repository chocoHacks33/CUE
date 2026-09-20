# Person A Stage 4 failure and access gate

Run this on the exact integration commit on D's Mac. Fixtures and replay clips
may debug a failure, but they cannot fill a row marked `LIVE`.

## Before testing

- Record the commit SHA, Mac/browser versions, LiveKit region/network and start time.
- Confirm all three Windows publishers are physically labelled and visible.
- Confirm `CAM-HOST` remains the sole programme microphone.
- Start in ASSIST. Do not enable AUTO merely because this checklist passes;
  B, C and D have separate Stage 4 gates.

## Routing and reconnect — 20 LIVE trials, zero swaps

For every row, record the physical laptop, expected camera ID, identity before
and after, track SID before and after, stream epoch and PASS/FAIL. A reconnect
passes only when the physical laptop returns to the same fixed slot, gets a new
track/epoch where required and never appears under another camera ID.

| Trial IDs | Action | Count |
|---|---|---:|
| `route-01`–`route-05` | Reload/rejoin `CAM-HOST` | 5 |
| `route-06`–`route-10` | Reload/rejoin `CAM-GUEST` | 5 |
| `route-11`–`route-15` | Reload/rejoin `CAM-WIDE` | 5 |
| `route-16`–`route-18` | Rejoin in a different physical order | 3 |
| `route-19` | Attempt a duplicate publisher for an occupied slot; it must be refused | 1 |
| `route-20` | Stop/change/restart the selected camera device; slot must remain fixed | 1 |

## Source loss — 10 LIVE trials

Run at least three losses while the failed camera is live, three while it is
standby, two during MANUAL HOLD, one with the wide view unavailable and one
after a republish. Record sustained-loss start and the first rendered safe
frame/slate. Every trial must select only an approved healthy source, preserve
the host audio policy and report a latency. The gate requires p95 ≤ 1,500 ms.

Use IDs `loss-01` through `loss-10`.

## Backend and provider failures — LIVE

| Trial ID | Injection | Required result |
|---|---|---|
| `backend-01` | Stop the control backend while media is live | D shows DEGRADED/local manual; current media and recording continue; recovery returns to ASSIST |
| `speech-01` | Make Deepgram unavailable or block its send path | One visible speech-down transition; no stale speech cut; manual switching remains usable |
| `semantic-01` | Make the semantic provider time out/fail | Safe HOLD/no target; no retry of an expired cue; manual switching remains usable |

## Event access and observer/control — automated minimum

Record at least one `EVENT_ACCESS` trial proving an invalid or other-event token
cannot enter the event. Record three `OBSERVER_CONTROL` trials: an observer's
`render.ack`, `render.reconcile` and `receiver.readiness` mutations must each be
refused with `OBSERVER_READ_ONLY`.

## JSON evidence

Copy `a-stage4-failure-report.template.json` to a result file and add one object
per trial:

```json
{
  "trialId": "loss-01",
  "area": "SOURCE_LOSS",
  "passed": true,
  "evidenceKind": "LIVE",
  "latencyMs": 1080,
  "detail": "CAM-GUEST blocked while live; first CAM-WIDE frame rendered"
}
```

Valid areas are `ROUTING_RECONNECT`, `SOURCE_LOSS`, `BACKEND_FAILURE`,
`SPEECH_PROVIDER_FAILURE`, `SEMANTIC_PROVIDER_FAILURE`, `EVENT_ACCESS` and
`OBSERVER_CONTROL`. Evaluate it from `apps/api`:

```powershell
cue-stage4-gate ..\..\docs\results\a-stage4-failure-report.json
```

Exit code 0 and `status: PASS` means A's operational gate passed. It does not
authorise named AUTO by itself. Preserve the JSON, recording and notes with the
tested commit.
