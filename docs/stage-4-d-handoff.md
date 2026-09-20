# Person D Stage 4 handoff: measurements, soak and failure hardening

Branch `codex/person-d-stage-4`, on top of the Stage 3 integration (trunk ea7e0d4). Date: 2026-09-19 (Boston).

Stage 4 for D in the v3 plan is a measurement stage: 20-minute three-feed soak, cut latency, A/V timing, disk recording and independent playback under full workload, plus the must-pass failure scenarios. The trials need real feeds and have not run. What shipped is the instrumentation that makes each trial a button press and an exported file, and the compositor-side failure hardening that can be proven offline. Results template: `docs/results/d-stage4-check.md`, every row NOT RUN.

## 1. Measurements in the compositor (`apps/web/src/compositor/measurements.ts`)

- **Cut latency.** Every APPLIED acknowledgement becomes a sample: press time, decision time, first drawn frame. For a backend-routed TAKE the press time is captured before the HTTP call and matched to the returned command, so the number is press-to-picture, not command-to-picture. Policy and safety cuts are recorded but do not count toward the manual-switching gate.
- **Failover timing.** A health-check failover opens a trial with the loss-detection time and the failed source's last-frame age; its APPLIED ack closes it with the drawn time. Both loss-detected-to-picture and from-last-frame are reported.
- **Gates** as in plan section 9: 30 operator cuts with p95 under 300 ms; 10 completed failovers with the slowest under 1.5 s. A trial that never drew fails the gate.
- Tests: `measurements.test.ts` (9).

## 2. Soak monitor (`apps/web/src/compositor/soak.ts`)

One sample a second while running: per-slot frame counters, last-frame age, renderable, epoch and track; the id of the audio track feeding the programme; draw interval and throttling; recorder phase, bytes and persist failures; JS heap where Chrome exposes it; control-link status. `summarizeSoak` folds that into per-slot ratios and gaps, audio-source changes, a least-squares heap slope and recorder health. `soakVerdict` applies the 20-minute gate: audio-source changes must be zero, throttling and persist failures must be zero, each slot renderable in at least 99% of samples; heap growth above 1 MB/min is flagged for review rather than passed. Tests: `soak.test.ts` (12).

The block at the bottom of the compositor shows the three rows live and exports one JSON with the samples, summaries, gates and the acknowledgement timeline (`Export Stage 4 measurements`).

## 3. Failure hardening (compositor side)

- **HOLD never waits for the network.** `requestMode("MANUAL_HOLD")` applies the local HOLD first and then tells the backend. A policy command computed against the pre-HOLD revision is rejected as `STALE_MODE_REVISION` even if it arrives before the backend answers. Before this, HOLD took effect only when the backend's snapshot came back. Test: `switcher.test.ts` "stage 4 failure scenarios".
- **AUTO is never resumed by the backend.** `modeToAdopt` in `controlAdapter.ts`: the compositor adopts AUTO from a backend snapshot only while the operator has pressed Enable AUTO here since the last connect, drop, HOLD or renderer generation. Otherwise it stays in ASSIST locally, parks policy commands as suggestions, asks the backend to step down to ASSIST, and shows a banner. This covers reconnect into ASSIST, a refused HOLD, and a backend restart. Tests: `controlAdapter.test.ts` "modeToAdopt" (3), `switcher.test.ts` (1).
- The seen-decision set is bounded for the soak.

## 4. A/V skew tool (`scripts/av_skew.py`)

Finds each flash (luminance step) and each clap (audio onset) in a recording, pairs them in order and reports per-pair skew and the p95 of the absolute skew against the 150 ms limit. Needs ffmpeg and numpy. Tested on synthetic ffmpeg clips with known offsets of +120, -80 and +40 ms, recovered within one source frame (35 ms tolerance), plus mismatch and no-flash cases: `apps/api/tests/test_av_skew.py` (6, skipped where ffmpeg is absent).

```bash
apps/api/.venv/bin/python scripts/av_skew.py programme.webm --events 6
```

## 5. Finding for the failover gate

Plan section 9 asks for a safe cut within 1.5 s of sustained loss detection. Today the receiver marks a slot stalled 1 s after its last frame (`STALL_THRESHOLD_MS`), and the switcher then waits a further 1.5 s of sustained loss (`FAILOVER_AFTER_MS`) before cutting, on a 250 ms health tick. So loss-detected-to-picture will measure about 1.6 to 1.8 s and from-last-frame about 2.6 to 2.8 s. The tool reports both. Nothing was retuned: the plan says measure first. If the team reads the gate literally, `FAILOVER_AFTER_MS` has to drop (1.0 s would leave 2.0 s from the last frame); if the stall threshold counts as the detection, the gate is already met by design. Decide after ten real trials.

## 6. Verification actually run (this Mac, 2026-09-19)

| Check | Result |
|---|---|
| `npm run typecheck` | clean |
| `npm test` | 192 passed (43 contracts, 149 web; 26 new) |
| `npm run build` | OK |
| `apps/api` pytest | 528 passed, 13 skipped (includes the 6 ffmpeg tests; the skips are B's OpenCV weights) |
| `apps/api` ruff, and ruff on `scripts/av_skew.py` | clean |

Not run: anything with a real feed. No camera has reached this Mac at any stage. Every row in `docs/results/d-stage4-check.md` is NOT RUN.

## 7. For A, B and C

- **A:** the compositor now sends `/mode ASSIST` on its own after a reconnect when the backend is in AUTO, with the snapshot's revision. If A prefers the backend to demote on director disconnect, do it there and the compositor's request becomes a no-op. Also: when the compositor applies HOLD locally first and the backend refuses it (`REVISION_CONFLICT`), the compositor stays holding and the next snapshot re-syncs; a banner shows the refusal.
- **B:** `GET /api/v1/guests/readiness` (#20) is not consumed by the compositor yet. Once #20 lands, D shows `disclosure` in the mode strip and records the naming policy in the Stage 4 exit-gate row.
- **C:** live cue latency (plan: 30 positive cues, p95 under 2.5 s from the final word) pairs C's decision log with the compositor's acknowledgement timeline. The export's `acks` carry `issuerDecisionId`, `atMs` (renderer clock) and the wall-clock export time; `scripts/latency_report.py --acks` is the join point.

## 8. Runbook

`docs/stage-0-d-mac-run.md`, section "Stage 4: measurements and failure drills".
