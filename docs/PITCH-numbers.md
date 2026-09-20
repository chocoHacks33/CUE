# CUE · Pitch numbers

_Table of every bracketed number in the pitch, the value it points at,
the results file it came from, and **NOT RUN** where no measurement
exists._

Rules:
- Do not hand-copy a value that was not measured. Missing → **NOT RUN**
  and the operator says so out loud.
- One JSON key per row. The row's `Source` is the exact `<file> → <key>`
  path so a re-run replaces the value without ambiguity.
- Values below are placeholders until step 5 of `scripts/latency_run.py`
  and `scripts/release_eval.py` run on the demo Mac. `scripts/soak_c_lane.py
  --minutes 2` has already produced its file on this Windows dev host and
  the four soak rows have their real numbers.

## Semantic quality

| Pitch number | Source | Value |
|---|---|---|
| Dev pass rate | `docs/results/C-release-eval.json → dev.pass_rate` | **NOT RUN** |
| Held-out pass rate | `docs/results/C-release-eval.json → heldout.pass_rate` | **NOT RUN** |
| Wrong SHOW cuts (held-out) | `docs/results/C-release-eval.json → heldout.wrong_cuts` | **NOT RUN** |

## Live latency

| Pitch number | Source | Value |
|---|---|---|
| Live end-to-end p50 (ms) | `docs/results/C-latency.json → hops.total_ms.p50` | **NOT RUN** |
| Live end-to-end p95 (ms) | `docs/results/C-latency.json → hops.total_ms.p95` | **NOT RUN** |
| Deepgram commit p50 (ms) | `docs/results/C-latency.json → hops.final_ms.p50` | **NOT RUN** |
| Deepgram commit p95 (ms) | `docs/results/C-latency.json → hops.final_ms.p95` | **NOT RUN** |
| Parser + policy p50 (ms) | `docs/results/C-latency.json → hops.cue_decide_ms.p50` | **NOT RUN** |
| Parser + policy p95 (ms) | `docs/results/C-latency.json → hops.cue_decide_ms.p95` | **NOT RUN** |

## Stability (2-min soak — this host)

Numbers below match `docs/results/C-soak.md` on `person-c-stage-7` at
commit `eb9e787`. Re-run `scripts/soak_c_lane.py --minutes 20` on the
Mac to replace with the 20-minute figures.

| Pitch number | Source | Value |
|---|---|---|
| Duplicate decisions | `docs/results/C-soak.md → duplicate_seqs` | 0 |
| Max queue depth | `docs/results/C-soak.md → max_queue_depth` | 1 |
| Log growth (bytes) | `docs/results/C-soak.md → log_bytes` | 59307 |
| Memory delta (MB) | `docs/results/C-soak.md → rss_delta_mb` | **NOT RUN** (Windows lacks `resource`; Mac 20-min run pending) |

## Morning re-establish

Filled in by `scripts/morning_check.py` and copied here after the Mac
run. Missing runs stay **NOT RUN**.

| Pitch number | Source | Value |
|---|---|---|
| Room SNR (dB) | `docs/results/C-stage7-morning.md → (b) Room noise SNR → snr_db` | **NOT RUN** |
| Host word accuracy | `docs/results/C-stage7-morning.md → (c) Speaker positions → host.accuracy` | **NOT RUN** |
| Guest word accuracy | `docs/results/C-stage7-morning.md → (c) Speaker positions → guest.accuracy` | **NOT RUN** |
| Deepgram first-word p50 (ms) | `docs/results/C-stage7-morning.md → (d) → first_word_ms_p50` | **NOT RUN** |
| Deepgram end-of-turn p50 (ms) | `docs/results/C-stage7-morning.md → (d) → eot_ms_p50` | **NOT RUN** |
| Full live-lane p95 (ms) | `docs/results/C-latency.json → hops.total_ms.p95` (via `latency_run.py` inside step (e)) | **NOT RUN** |

## Identity disclosure

| Pitch number | Source | Value |
|---|---|---|
| Identity mode on every decision | `LiveLane` → `DecisionRecord.identity` | `ROLE_BASED` unless B ships a `VERIFIED` face-identity provider before the demo |

## Do not paste anything above without a re-run

If a row above shows **NOT RUN**, the operator says at the top of the
demo: "we did not measure X on this hardware; the value in the pitch
that references X is intentionally left blank."
