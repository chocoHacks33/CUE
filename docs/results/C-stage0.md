# C-lane · Stage 0 status

_Owner: role C (speech, context, policy). Branch `person-c-stage-0`, branched from `codex/person-a-stage-0`._

## What exists

| Milestone | Deliverable | Location | State |
|---|---|---|---|
| M1 semantic brain | Pydantic `Cue` + `parse()` + `validate()` | `apps/api/src/cue_api/semantics/parser.py` | Ready to evaluate; no live run yet (needs `OPENAI_API_KEY`). |
| M1 dev corpus | 46 tuned cases | `scripts/data/adversarial.json` | Field key `target_guest_ids`. |
| M1 release corpus | 40 fresh cases (disjoint wording/shapes/guest names) | `scripts/data/heldout.json` | **Never used for tuning.** Access only through the pinned model + prompt at release. |
| Semantic runner | `--set dev\|heldout`, `--only CAT`, `--repeat N` | `scripts/run_semantic.py` | Writes `scripts/results_<set>_<model>_<ts>.json`. Ignored by git. |
| M5 director | Pure `decide(cue, cameras, state, now, *, role_based, role_map)` | `apps/api/src/cue_api/policy/director.py` | 23/23 unit tests green under A's pytest. No network, no LLM, no globals. |
| Contracts proposal to A | JSON Schemas + fixtures for `Cue` / `Decision` / `State` | `docs/contracts-proposal/` | Six/four/four fixtures each; every fixture validates against its type. A owns `packages/contracts/`; this is a proposal. |
| Ops smoke | Verifies both keys and hits each provider once | `scripts/smoke_api.py` | Never prints a key; exits non-zero on any failure. |

**Provider policy (updated).** OpenAI stays the production runtime and the default: `CUE_PROVIDER=openai` in `.env.example`, `parse()` targets the OpenAI SDK, and release-gate measurements are always on the pinned OpenAI model. Ollama is a **dev-only fallback** used when the OpenAI key is temporarily unavailable to a teammate (the shared key currently lives on A's machine); it is not a supported production interpreter and it does not participate in the release gate. Any Ollama-branching code lives outside the release path — see `scripts/smoke_api.py` on the `person-c-booth-demo` branch for the dev-only reachability check.

## Local model findings: CPU only, not viable for production

Booth-demo latency exploration on this laptop. **Recorded here so we do not re-run these experiments; the conclusion is to park the local-model path.** Production continues to target OpenAI.

**Hardware context.** `ollama ps` shows 100% CPU across every model I ran; the laptop has no GPU acceleration available to Ollama. That is the ceiling every number below sits under.

| model | processor | context | resident size |
|---|---|---|---|
| llama3.2:3b   | 100% CPU | 4096 | 2.6 GB |
| llama3.2:1b   | 100% CPU | 4096 | 1.5 GB |
| qwen2.5:1.5b  | 100% CPU | 4096 | 1.2 GB |

**Sequential-parse benchmark, `scripts/bench_ollama.py --model llama3.2:3b --n 10`** (warm; first-call excluded from steady-state):

| mode | first-call | steady p50 | steady p95 | mean tokens/call |
|---|---:|---:|---:|---:|
| full-schema Cue    | 19 930 ms | 5 890 ms | 6 149 ms | 58 |
| fast-schema (this branch) |  8 395 ms | 4 243 ms | 4 697 ms | 30 |

Fast mode halves output tokens and cuts steady p50 by ~28% on the 3B model, but the CPU floor still dominates.

**Dev-set (46 cases) in fast mode, `scripts/run_semantic.py --set dev`:**

| model | pass rate | wrong SHOW cuts | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|
| qwen2.5:1.5b | 80.4 % | 4 | 3 582 | 3 911 |
| llama3.2:3b  | 76.1 % | 6 | 4 323 | 4 670 |
| llama3.2:1b  | 65.2 % | **0** | 3 988 | 4 977 |

**Conclusion.** Booth target was p50 < 1.5 s with zero wrong cuts and 80%+ pass. **No local model on this laptop clears both bars simultaneously**, and the fastest p50 is still ~2.4× the target. The bottleneck is CPU-only, JSON-schema-constrained decoding of the tokens themselves; smaller models and fast-mode schema shrinkage do not close the gap enough. Decision: **park the local Ollama path**, do not pursue further optimisation there (including plain-text output), and ship the release path on OpenAI as originally planned. All Ollama-branching code stays on `person-c-booth-demo` and is not merged into the release path.

## Run commands (from `apps/api`'s venv)

A's onboarding sequence still works verbatim:

```bash
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Then, from repo root:

```bash
# A's checks (I match these exactly):
cd apps/api && python -m pytest -q      # includes my 23 director tests
cd apps/api && python -m ruff check .   # my files were fixed to pass A's E/F/I/B/UP rules

# C-lane extras (from repo root, apps/api's venv activated):
python scripts/run_semantic.py --models <id>              # dev set (default)
python scripts/run_semantic.py --models <id> --set heldout
python scripts/smoke_api.py                                # verify OPENAI + DEEPGRAM keys
```

Category filter: `--only NOW|FUTURE|NEGATED|PAST|MENTION|CORRECTION|GROUP|RETURN|AMBIGUOUS`.
Repeat for jitter: `--repeat N`.

## Dependency additions to `apps/api/pyproject.toml`

A's `pyproject.toml` did not include `openai` or `python-dotenv`. I added them in a **separate small commit** on this branch (see `git log`). `pydantic` did not need adding — it already ships transitively via `pydantic-settings`.

The addition looks like:

```toml
dependencies = [
  ...
  "openai>=1.50,<4",
  "python-dotenv>=1.0,<2",
]
```

If A prefers a different pinning strategy or wants these under `optional-dependencies.semantics`, I'll adapt.

## What I need from A

1. **Master PCM audio interface (M4 unblocker).** A's worker ingest must expose an async generator (or callback) of decoded PCM frames with, per chunk:
   - `master_track_sid`, `audio_epoch`, `sample_rate_hz`, `channels`, `sample_format` (int16/float32), `sample_offset` (monotonic within epoch), `receive_time` (backend clock seconds).
   - Guarantee: no silent sample-rate/format switch inside an epoch. On re-publish or codec change → new `audio_epoch`.
   - Capacity: back-pressure via a bounded queue; C resamples once at the boundary if the rate isn't the configured target (16 kHz mono int16 for Deepgram).
2. **Camera state shape used at policy call time.** Confirm A will publish, per camera, the exact dict shape the director consumes: `{role: "host"|"guest"|"wide", healthy: bool, epoch: int, confirmed_guest_ids: [str], evidence_age_s: float}`. `confirmed_guest_ids` and `evidence_age_s` come from B; `role`/`healthy`/`epoch` are A. A's existing `CameraRole` enum uses uppercase `HOST|GUEST|WIDE`; I'm happy to switch my director to accept A's enum values verbatim — just pick a shape and freeze it.
3. **Contracts folder ownership.** A owns `packages/contracts/`; my proposals live in `docs/contracts-proposal/`. Please tell me whether to raise a PR from that folder or hand over the files for you to place under `packages/contracts/`. Names/fields do not collide with A's existing contracts (see side-by-side below).
4. **Cue transport.** Once we settle on serialization (JSON over the internal WS in section 5 of the plan), I'll adopt whichever `utterance_id` scheme A prefers. Current default: string, opaque, minted by C at utterance boundary. `created_at` uses backend seconds.

## Contracts side-by-side

| A's `apps/api/src/cue_api/contracts.py` | C's `docs/contracts-proposal/` |
|---|---|
| `CameraId` (StrEnum: CAM-HOST/GUEST/WIDE) | — |
| `CameraRole` (StrEnum: HOST/GUEST/WIDE) | — |
| `AudioPolicy` (StrEnum: MASTER/DISABLED) | — |
| `CameraContract` | — |
| `PublisherTokenRequest` / `PublisherTokenResponse` | — |
| `TopologyResponse`, `HealthResponse` | — |
| — | `Cue` (target_guest_ids, scope, intent, temporal_intent, action, evidence_text, utterance_id, created_at) |
| — | `Decision` (action ∈ TAKE/STAY/SLATE, camera_id, reason) |
| — | `State` (current_camera, last_cut_time, mode ∈ AUTO/ASSIST/HOLD, hold_until, last_utterance_id) |

Zero name collisions. A's contracts describe camera admission/routing/health; mine describe semantic interpretation and directing policy. I did not touch A's `contracts.py`.

## What I hand over

- **Cue** — pydantic model of one utterance's meaning. Pure output; consumers must call `validate()` before trusting `target_guest_ids` against a roster.
- **decide()** — pure directing function. Threadsafe, no I/O. See `apps/api/src/cue_api/policy/director.py` for full docstring; constants are `MIN_SHOT_S=2.5`, `CUE_LIFETIME_S=3.0`, `IDENTITY_MAX_AGE_S=1.5`.
- **State** — caller-owned; the caller mutates `current_camera`, `last_cut_time`, `last_utterance_id` after each successful `TAKE`, and sets `mode`/`hold_until` on producer input.
- **Contracts proposal** — three JSON Schemas + 14 fixtures at `docs/contracts-proposal/`. A can lift these into `packages/contracts/` as-is; every fixture instantiates against the current Python types.
- **Held-out semantic set** — `scripts/data/heldout.json`. Reviewers must not read cases before running the release gate; keep the file closed in the tuning loop.

## Known gaps and risks

- **No live latency numbers yet.** M1 pass rate + p50/p95 pending an OpenAI key. `scripts/smoke_api.py` gates that.
- **`openai` SDK version pinning.** `pip install openai>=1.50,<4` on this machine currently resolves to `openai-3.16.2`. Both `client.models.list()` and `client.responses.parse` exist on that release, so the smoke and parse paths look intact. If A wants a stricter upper bound (e.g., `<2`), C will match.
- **Provider is a single point of failure.** With `CUE_PROVIDER=openai` and no fallback code, an OpenAI outage silently degrades the demo to ASSIST/manual. Documented in `.env.example`; retry/timeout policy on `parse()` is minimal (single try, safe HOLD on any exception).
- **Roster expansion.** `apps/api/src/cue_api/semantics/roster.json` now has 7 guests (was 3). The extra names (`maya`, `alex`, `jordan`, `kai`) are used by the held-out set. If A/B/D depend on the 3-guest roster anywhere, flag it and I'll gate the extras behind an event id or move them to a fixture-only roster.
- **CameraRole case mismatch.** A's `CameraRole` enum uses uppercase (`HOST`/`GUEST`/`WIDE`); my director reads `cameras[cid]["role"]` as lowercase (`host`/`guest`/`wide`). Not blocking today — my tests fabricate the dict directly — but on wiring day one of us will normalize. Trivial to adapt on my side.

## Immediate next steps (still on C)

1. Once `OPENAI_API_KEY` is available: `python scripts/smoke_api.py`, then M1 dev → M1 held-out. Save results as `docs/results/C-m1-<model>.md`.
2. Wait on A's PCM interface. When ready, wire the audio adapter → Deepgram → `parse()` (M4).
3. Wire `decide()` into A's control transport under the shape A commits to.
