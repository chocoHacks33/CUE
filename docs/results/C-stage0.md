# C-lane · Stage 0 status

_Owner: role C (speech, context, policy). Branch `codex/c-speech-policy`._

## What exists

| Milestone | Deliverable | Location | State |
|---|---|---|---|
| M1 semantic brain | Pydantic `Cue` + `parse()` + validator | `services/worker/semantics/parser.py` | Ready to evaluate; no live run yet (needs `OPENAI_API_KEY`). |
| M1 dev corpus | 50 tuned cases | `tests/semantics/adversarial.json` | Field key renamed to `target_guest_ids`. |
| M1 release corpus | 40 fresh cases, disjoint wording/shapes/guests | `tests/semantics/heldout.json` | **Never used for tuning.** Access only through the pinned model + prompt at release. |
| M5 director | Pure `decide(cue, cameras, state, now, *, role_based, role_map)` | `services/api/policy/director.py` | 23/23 unit tests green. No network, no LLM, no globals. |
| Contracts proposal to A | JSON Schemas + fixtures for `Cue` / `Decision` / `State` | `docs/contracts-proposal/` | Six/four/four fixtures each; every fixture validates against its type. |
| Ops smoke | Verifies both keys and hits each provider once | `scripts/smoke_api.py` | Never prints a key; exits non-zero on any failure. |

Team decision recorded: `CUE_PROVIDER=openai` is the sole semantic interpreter for the runtime. `.env.example` documents the constraint. No Ollama or alt-provider code exists; do not add any.

## Run commands

```bash
# Dev semantics (tuning; requires OPENAI_API_KEY + CUE_MODEL)
python tests/semantics/run_semantic.py --models <model_id>

# Release semantics (measured once per pinned model + prompt)
python tests/semantics/run_semantic.py --models <model_id> --set heldout

# Director unit tests (offline, deterministic)
pytest tests/policy

# Live-provider smoke (no key prints, no billing surprise)
python scripts/smoke_api.py
```

Category filter: `--only NOW|FUTURE|NEGATED|PAST|MENTION|CORRECTION|GROUP|RETURN|AMBIGUOUS`.
Repeat for jitter: `--repeat N`.

## What I need from A

1. **Master PCM audio interface (M4 unblocker).** For the semantic worker to consume master audio, A's worker ingest must expose an async generator (or callback) of decoded PCM frames with, per chunk:
   - `master_track_sid`, `audio_epoch`, `sample_rate_hz`, `channels`, `sample_format` (int16/float32), `sample_offset` (monotonic within epoch), `receive_time` (backend clock seconds).
   - Guarantee: no silent sample-rate/format switch inside an epoch. On re-publish or codec change → new `audio_epoch`.
   - Capacity: back-pressure via a bounded queue; C resamples once at the boundary if the rate isn't the configured target (16 kHz mono int16 for Deepgram).
2. **Camera state shape used at policy call time.** Confirm A will publish, per camera, the exact dict shape the director consumes: `{role: "host"|"guest"|"wide", healthy: bool, epoch: int, confirmed_guest_ids: [str], evidence_age_s: float}`. `confirmed_guest_ids` and `evidence_age_s` come from B; `role`/`healthy`/`epoch` are A. If A prefers a Pydantic model for this, I'll adapt on my side — just pick a shape and freeze it.
3. **Contracts folder ownership.** A owns `packages/contracts`; my proposals are in `docs/contracts-proposal/`. Please tell me whether to raise a PR from that folder or hand over the files for you to place under `packages/contracts/`.
4. **Cue transport.** Once we settle on serialization (JSON over the internal WS in section 5 of the plan), I'll adopt whichever `utterance_id` scheme A prefers. Current default: string, opaque, minted by C at utterance boundary. `created_at` uses backend seconds.

## What I hand over

- **Cue** — model of one utterance's meaning. Pure output; consumers must call `validate()` (in `parser.py`) before trusting `target_guest_ids` against a roster.
- **decide()** — pure directing function. Threadsafe, no I/O. See `services/api/policy/director.py` for full docstring; constants are `MIN_SHOT_S=2.5`, `CUE_LIFETIME_S=3.0`, `IDENTITY_MAX_AGE_S=1.5`.
- **State** — caller-owned; the caller is expected to mutate `current_camera`, `last_cut_time`, `last_utterance_id` after each successful `TAKE`, and set `mode`/`hold_until` on producer input.
- **Contracts proposal** — three JSON Schemas + 14 fixtures at `docs/contracts-proposal/`. A can lift these into `packages/contracts/` as-is; every fixture instantiates against the current Python types.
- **Held-out semantic set** — `tests/semantics/heldout.json`. Reviewers must not read cases before running the release gate; keep the file closed in the tuning loop.

## Known gaps and risks

- **No live latency numbers yet.** M1 pass rate + p50/p95 are pending an OpenAI key. `smoke_api.py` gates that.
- **`openai` SDK version.** `pip install -r requirements.txt` on this machine resolved `openai-3.16.2` (via a transitive `httpx2`), which is not the canonical `openai==1.x` API surface most examples target. `client.models.list()` and `client.responses.parse` both exist on the installed client, so smoke and parse paths look intact, but a preflight run against a real key is still required. If A pins a specific `openai` version in a shared `requirements` file, C will match.
- **Provider is a single point of failure.** With `CUE_PROVIDER=openai` and no fallback code, an OpenAI outage silently degrades the demo to ASSIST/manual. Documented in `.env.example`; retry/timeout policy on `parse()` is minimal (single try, safe HOLD on any exception).
- **Roster expansion.** `services/worker/semantics/roster.json` now has 7 guests (was 3). The extra names (`maya`, `alex`, `jordan`, `kai`) are used by the held-out set. If A/B/D depend on the 3-guest roster anywhere, flag it and I'll gate the extras behind an event id or move them to a fixture-only roster.
- **`services/api/` container.** I created `services/api/policy/` (my lane) without touching A's neighbouring folders (`auth`, `devices`, `control`, `logs`, `guests`). No `__init__.py` at `services/` or `services/api/` — imports work via `tests/conftest.py` `sys.path` insertion. A may prefer explicit packaging; happy to add `__init__.py` at A's call.
- **CLAUDE.md min-shot value.** Reconciled to 2.5 s (was 1.5 s). If anyone else's code baked in 1.5 s during Stage 0, that's their bug now.

## Immediate next steps (still on C)

1. Once `OPENAI_API_KEY` is available: run `smoke_api.py`, then M1 dev → M1 held-out. Save results as `docs/results/C-m1-<model>.md`.
2. Wait on A's PCM interface. When ready, wire the audio adapter → Deepgram → `parse()` (M4).
3. Wire `decide()` into A's control transport under the shape A commits to.
