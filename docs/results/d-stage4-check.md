# D Stage 4 check: soak, cut latency, A/V timing, recording under load

Status: **NOT RUN — needs the three Windows publishers, the master mic and the worker on this Mac.**

Leave a row as NOT RUN until it was actually run. Recordings and exports are private artifacts, not committed. The tooling that fills each row shipped in `docs/stage-4-d-handoff.md`; nothing below is a claim until the export exists.

Commit tested: `________________`

Operator / date / network: `________________`

Mac configuration at the time (browser version, worker running, OpenCV extra installed): `________________`

## 1. Manual switching (plan section 9: at least 30 cuts, p95 TAKE-to-render below 300 ms)

Source: the compositor's Stage 4 block, "Manual cuts" row, and the `cuts` section of the exported JSON.

| Item | Result | Evidence |
|---|---|---|
| Operator cuts counted | NOT RUN | |
| Press-to-picture p50 / p95 / max (ms) | NOT RUN | |
| Decision-to-picture p95 (ms), backend-routed cuts | NOT RUN | |
| Gate | NOT RUN | |

## 2. Preview delay (A/D: visible timer or flash, p95 below 800 ms)

Manual: point a camera at a running stopwatch, photograph the Mac screen and the stopwatch together, read the difference. Ten readings per camera.

| Camera | Readings (ms) | p95 | Result |
|---|---|---|---|
| CAM-HOST | | | NOT RUN |
| CAM-GUEST | | | NOT RUN |
| CAM-WIDE | | | NOT RUN |

## 3. Failover (plan section 9: 10 deliberate failures, safe cut within 1.5 s of sustained loss detection)

Source: "Failovers" row and the `failovers` section of the export. Cover the webcam, close the lid or pull the publisher tab; note which for each trial.

| Trial | Failed camera | How | Loss detected to safe picture (ms) | From last frame (ms) | Target |
|---|---|---|---|---|---|
| 1 to 10 | | | NOT RUN | | |

Gate: NOT RUN. Read `docs/stage-4-d-handoff.md` section 5 before judging this row: the switcher waits 1.5 s of sustained loss before cutting, on top of the 1 s stall threshold, so the literal gate is expected to read about 1.6 to 1.8 s until the constants are tuned from these numbers.

## 4. A/V timing (plan section 9: recorded output p95 absolute skew below 150 ms)

Clap in front of a visible light three times at the start and three times after 15 minutes, per camera angle used. Then:

```bash
apps/api/.venv/bin/python scripts/av_skew.py <programme recording> --events 6
```

| Recording | Angle | Pairs found | p95 abs skew (ms) | Mean skew (ms, + = audio late) | Verdict |
|---|---|---|---|---|---|
| | | | NOT RUN | | |

## 5. 20-minute soak (plan section 9: all publishers, worker, inference and recorder; no unbounded memory growth or audio-source change)

Start the programme recording, then "Start 20-minute soak", then leave everything running. Stop the soak, export, stop the recording.

| Check | Result | Evidence |
|---|---|---|
| Duration sampled | NOT RUN | |
| Audio-source changes (must be 0) | NOT RUN | |
| Heap first / last / slope per minute | NOT RUN | |
| Draw loop throttled samples (must be 0) | NOT RUN | |
| Per-slot renderable ratio, stalls, max frame gap | NOT RUN | |
| Recorder persist failures (must be 0) | NOT RUN | |
| Mac CPU / memory pressure during the run (Activity Monitor) | NOT RUN | |
| Verdict from the export | NOT RUN | |

## 6. Disk recording and independent playback under full workload

| Item | Result | Evidence |
|---|---|---|
| Recording file size, duration, container | NOT RUN | |
| Plays in QuickTime or VLC from start to end | NOT RUN | |
| Audio continuous across every cut | NOT RUN | |
| Private artifact location | | |

## 7. Failure drills (plan section 9, must-pass scenarios in D's lane)

| Scenario | Automated proof | Live drill |
|---|---|---|
| Late policy command after HOLD is rejected | `switcher.test.ts` "stage 4 failure scenarios" | NOT RUN |
| Backend restart (new control generation) drops pending work | `switcher.test.ts` "backend control sync" | NOT RUN |
| Control link drops: DEGRADED, local manual controls keep working | Stage 3 | NOT RUN |
| Reconnect does not resume AUTO; operator re-arms it | `controlAdapter.test.ts` "modeToAdopt" | NOT RUN |
| Missed ACK: FAILED after 1 s and revert | `switcher.test.ts` "failed acknowledgement" | NOT RUN |
| Recorder or storage fails: banner, chunks preserved, live view continues | Stage 3 | NOT RUN |
| Programme browser restart: new renderer generation, fresh readiness, new recording file | Stage 2 | NOT RUN |

## 8. Exit gate decision (plan Stage 4: named AUTO only if evidence supports it)

B's readiness endpoint (`GET /api/v1/guests/readiness`, PR #20) returns the naming policy and disclosure text. At the time of writing it returns ROLE_BASED. Record here what the show will run in and why.

Decision: NOT DECIDED. Disclosure text shown to the audience: `________________`
