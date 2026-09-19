# CUE: context-aware live director (HackMIT, 24h, 4 people)

Pitch: "Other automatic cameras follow who's talking. CUE follows what's happening."

## What we are building
Phones stream video to a laptop. The host's speech is transcribed live.
An LLM turns each clause into a structured meaning (who, intent, timing).
A deterministic director (plain code, no LLM) decides: SHOW, WIDE, HOST or HOLD.
Correctly deciding NOT to cut is a core feature.

## Stack
- Video: LiveKit Cloud (WebRTC). UI: React + TypeScript (Vite).
- Backend: Python 3.11+, FastAPI. Speech: Deepgram streaming.
- Meaning: OpenAI structured output (see apps/api/src/cue_api/semantics/parser.py).
- Face identity (YuNet + SFace) is optional and last.

## Hard rules
1. The LLM never picks a camera. It outputs meaning only.
2. Never hard-code a demo sentence. Never fake a live result.
3. When unsure, HOLD or WIDE. A wrong confident cut is the worst outcome.
4. Two reliable cameras beat three unstable ones.
5. Master audio never restarts when video cuts.
6. Secrets live in .env. Never print or commit keys.
7. Do not add features outside the current milestone. Ask first.
8. Never say something works unless you ran it. Show the command and output.

## Milestones (finish and test each before the next)
- M1 Semantic brain passes tests/adversarial.json at 90%+ with p95 latency measured.
- M2 One phone feed visible on the laptop.
- M3 Two or three feeds, manual switching, continuous audio.
- M4 Live mic -> Deepgram -> clauses -> semantic JSON on screen.
- M5 Roster maps subject to camera (sarah = Camera B). SHOW drives the switcher.
- M6 Judge panel: transcript, subject, intent, timing, action, camera, latency.
- M7 Optional: face identity. Kill it fast if unreliable.

## Clause and correction rule
Act on each finished clause for speed. If a correction follows within the
same utterance ("Sarah, actually Daniel"), allow one fast re-cut. Minimum
shot length 2.5 s otherwise (matches v3 plan section "Directing logic C owns").

## How to work with me
- Start every reply by naming the milestone you are advancing.
- Smallest reliable implementation. Short sequential steps.
- Every code change comes with a run command and a concrete test.
- Flag assumptions. Check library APIs against the installed version.
- Commit after each passing gate: `git commit -am "M<n>: <what passed>"`.

## Commands (run from apps/api's venv unless noted)
- Install: `cd apps/api && python -m pip install -e ".[dev]"`
- Pytest (A's convention): `cd apps/api && python -m pytest -q`
- Ruff (A's convention):   `cd apps/api && python -m ruff check .`
- Semantic runner:         `python scripts/run_semantic.py --models <id> [--set dev|heldout]`
- Provider smoke:          `python scripts/smoke_api.py`

## Layout (matches A's Stage-0 monorepo)
apps/api/src/cue_api/            FastAPI backend (A) + C-lane modules:
apps/api/src/cue_api/semantics/     parser, prompt, schema, roster (C)
apps/api/src/cue_api/policy/        deterministic director (C)
apps/api/src/cue_api/{contracts,livekit_tokens,main,settings}.py  (A)
apps/api/tests/                  pytest collects here (A + C tests colocated)
apps/web/                        React publisher (A, D)
packages/contracts/              TypeScript contracts package (A)
scripts/                         run_semantic.py, smoke_api.py, data/
docs/contracts-proposal/         C's proposed Cue/Decision/State schemas
docs/results/                    Stage handoff and eval reports
