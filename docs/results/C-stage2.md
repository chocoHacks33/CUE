# C-lane · Stage 2 status

_Branch `person-c-stage-2`, based on `person-c-stage-1` (A's Stage-1 base + my Stage-1 delivery)._

## What went in

| Source | Files | Purpose |
|---|---|---|
| Merged `origin/person-c-stage-2-prep` | `apps/api/src/cue_api/c_lane.py`, `policy/session.py`, `policy/log.py`, `semantics/queue.py`; matching tests; `docs/C-INTEGRATION.md`, `docs/contracts-proposal/decision_record.schema.json`, `docs/results/C-stage2-prep.md`; `scripts/fixture_cues.py` | Stage-2 offline core: `DirectorSession`, `SemanticQueue`, `DecisionLogger`, `CLane` façade, integration doc, fixture replay. |
| Cherry-picked from `person-c-desk-prototype` | `apps/api/src/cue_api/policy/explain.py` + `apps/api/tests/test_explain.py` + `apps/api/src/cue_api/semantics/roster.json` | `plain_reason(record) -> str` with the CUE-vs-you rule and per-guest pronouns. |
| New here | `apps/api/src/cue_api/policy/wire.py`, `apps/api/tests/test_wire.py`, updated `scripts/fixture_cues.py` | Adapter from my `DecisionRecord` into A's control-transport shape (camelCase, `contractVersion="0.1.0"`); every fixture line tagged `"source": "FIXTURE"`. |

No A/B/D file was edited. The wire adapter lives in `cue_api.policy` (C-owned) exactly because A hasn't defined a producer→compositor decision transport contract yet; when they do, this module can be renamed or replaced without churn in `parser.py`, `session.py`, or `log.py`.

## The wire adapter (fixture cue producer output)

`cue_api.policy.wire.DecisionEvent` is a pydantic `BaseModel` with A's alias generator (`to_camel`) so field names round-trip snake_case in Python and camelCase on the wire. Envelope shape:

```jsonc
{
  "contractVersion": "0.1.0",
  "kind": "decision",
  "at": 1000.5,
  "decisionSeq": 3,
  "modeRevision": 1,
  "action": "TAKE",
  "cameraId": "CAM-GUEST",
  "reason": "role_based: sarah -> CAM-GUEST",
  "plainReason": "CUE cut to Sarah. She was just invited up.",
  "transcriptSpan": {
    "utteranceId": "utt-42",
    "text": "Please welcome Sarah Tan.",
    "startedAt": null,
    "endedAt": 1000.0
  },
  "cueSummary": {
    "targetGuestIds": ["sarah"],
    "scope": "single",
    "temporalIntent": "NOW",
    "actionPreValidate": "SHOW"
  },
  "camerasConsidered": [ ... ],
  "latenciesMs": { "asr": 320, "cue": 850, "decide": 1, "total": 1171 },
  "source": "FIXTURE"
}
```

`source` is `"LIVE"` for real decisions and `"FIXTURE"` for the scripted timeline. Any garbage or absent value is clamped back to `"LIVE"` in the adapter so no client can spoof itself into thinking a fixture is live.

## Fixture cue producer

`scripts/fixture_cues.py` is unchanged in its scripted timeline (future mention, immediate intro, guest camera covered, manual HOLD, late-cue-stale-mode-rev, RESUME_AUTO, correction) but now emits wire-format by default:

```bash
python scripts/fixture_cues.py                    # wire format (default)
python scripts/fixture_cues.py --format raw       # DecisionRecord.to_json()
python scripts/fixture_cues.py --out demo.jsonl   # also append raw records to a log
```

Verified on this branch:

```
seq=1 rev=0 action=STAY camera=CAM-HOST source=FIXTURE version=0.1.0 plain=Staying on the host. Sarah is joining later.
seq=2 rev=0 action=TAKE camera=CAM-GUEST source=FIXTURE version=0.1.0 plain=CUE cut to Sarah. She was just invited up.
seq=3 rev=0 action=TAKE camera=CAM-WIDE source=FIXTURE version=0.1.0 plain=Sarah's camera isn't usable, so showing the wide shot.
seq=4 rev=1 action=STAY camera=CAM-WIDE source=FIXTURE version=0.1.0 plain=You took over. CUE is waiting.
seq=5 rev=1 action=STAY camera=CAM-WIDE source=FIXTURE version=0.1.0 plain=Ignoring a late suggestion. Your last command wins.
seq=6 rev=2 action=STAY camera=CAM-WIDE source=FIXTURE version=0.1.0 plain=CUE is directing again.
seq=7 rev=2 action=TAKE camera=CAM-GUEST source=FIXTURE version=0.1.0 plain=CUE cut to Daniel. He was just invited up.
```

## Tests

`218 passed, 2 warnings in 4.84s` (`180` baseline from stage-2-prep merge on top of the Stage-1 tree, `+ 29` `test_explain.py` cases brought from desk-prototype, `+ 9` new `test_wire.py` cases).

`ruff check .`: **All checks passed** with A's config (`E, F, I, B, UP`).

## Run commands D uses on the Mac

```bash
# 1. Install (A's convention; C's extras are optional).
cd apps/api && python -m pip install -e ".[dev]"

# 2. CI-equivalent checks.
cd apps/api && python -m ruff check .
cd apps/api && python -m pytest -q

# 3. Fixture cue stream (JSON-lines to stdout in A's wire shape).
python scripts/fixture_cues.py

# 4. Fixture cue stream to a log file (also emits raw DecisionRecord log lines).
python scripts/fixture_cues.py --out /tmp/cue-fixture-run.jsonl

# 5. Point A's compositor at the fixture stream:
python scripts/fixture_cues.py | your-compositor-consumer.py
```

`docs/C-INTEGRATION.md` (from stage-2-prep) has the eight-method `CLane` surface for the live path (Deepgram → assembler → parser → decide → emit). The wire adapter plugs into `CLane`'s `emit` callback: A's transport code becomes `emit = lambda rec: control_ws.send_json(wire.to_wire_json(rec))`.

## Open requests

**A — decision transport contract.**
- Please formalise the producer↔compositor decision channel (WS path, framing, ack format) so I can drop the `cue_api.policy.wire.DecisionEvent` in as-is. The current envelope follows A's `contractVersion` + `to_camel` conventions; if A prefers pydantic `BaseModel` in `apps/api/src/cue_api/contracts.py` and a subclass of `ContractModel`, I'll adapt (the shape stays the same).
- If A wants event-scoped rosters served from `/api/v1/events/{event}/roster`, tell me and I'll change `cue_api.semantics.roster` to consume that.
- The PCM contract (`DecodedAudioChunk`) is already the input to my `cue_api.speech.deepgram_stream` (see `docs/results/C-stage1.md`). Give me the actual Deepgram connection object (or a factory) and the ingest-chunk cadence and I can wire this up on Stage 3.

**B — camera evidence.**
- The director's `cameras` dict needs `confirmed_guest_ids: list[str]` and `evidence_age_s: float` per camera. Confirm the tick cadence and freshness contract you plan to give me, and whether you also want to publish `guest_ready: bool` from your side (I honour it if present; default `True`).
- Roster IDs must be exactly the strings I use (`sarah`, `daniel`, `priya`, `maya`, `alex`, `jordan`, `kai`).

**D — compositor.**
- The wire `DecisionEvent` includes `plainReason` alongside `reason`. If you want the producer overlay to render only `plainReason`, that's the field; `reason` stays for the operational log.
- Every decision carries `decisionSeq`; ack every applied cut back through `CLane.on_ack(decision_seq, applied=True, now)`.
- `source == "FIXTURE"` means don't render as live: hint in the UI or drop it entirely — never confuse a scripted line for a live one.
- Deepgram interim results also produce a `plainReason`-shaped envelope in the desk prototype, but Stage-2's `CLane.emit` only fires on decisions. If you want captions on the WS, tell me and I'll add a separate `kind: "caption"` event.
