# C-lane · Stage 2 prep

_Branch `person-c-stage-2-prep`, branched from `person-c-stage-1-prep`. Guest-ready gate cherry-picked from `person-c-booth-demo` (`e46b4b5`). No live_demo.py, no Ollama fast-mode code, no booth-demo residue._

## What this branch adds (offline only)

All new modules live under `apps/api/src/cue_api/` and are pure Python + stdlib + existing deps (pydantic transitively). Nothing here hits the network, opens a socket, or spawns a thread.

| Module | Purpose |
|---|---|
| `apps/api/src/cue_api/policy/session.py` | `DirectorSession`. Owns `State` and wraps `decide()`. Adds `decision_seq`, `mode_revision`, ACK handling, and the AUTO-pause rules the plan requires. |
| `apps/api/src/cue_api/semantics/queue.py` | `SemanticQueue`. One-in-flight / latest-pending coalescing wrapper. Older pending utterances are dropped and logged. Queue-level timeout produces a safe HOLD cue. `parse_fn` injected. Tags each returned cue with the `mode_revision` captured at submit. |
| `apps/api/src/cue_api/policy/log.py` | `DecisionRecord` + append-only `DecisionLogger`. One JSON object per line: transcript span, cue summary, cameras considered (with rejection reasons), reason, latencies, `source: LIVE\|FIXTURE`. |
| `scripts/fixture_cues.py` | Offline scripted timeline: future mention, immediate intro, guest camera covered, manual HOLD, late cue (stale mode_revision), correction. Every emitted line is `source: FIXTURE`. |

## Rules encoded in `DirectorSession` (from plan §5, "Directing logic C owns")

- **Manual HOLD defeats pending/late AI decisions.** Every manual command (`TAKE cam`, `HOLD`, `RESUME_AUTO`, `SLATE`) increments `mode_revision`. `SemanticQueue` stamps each cue with the `mode_revision` that was current when the utterance was submitted for parsing. `on_cue()` rejects any cue whose stamped `mode_revision` doesn't match the session's current one — so a slow LLM answer for a cue that was interpreted before the producer pressed HOLD arrives after HOLD and is dropped with reason `"cue from stale mode_revision X (current Y)"`.
- **Emergency/failure safety still works during HOLD.** `on_cue()` while paused delegates to `decide()` with mode temporarily forced to `HOLD`; `decide()`'s `_safe_fallback` still failovers to a healthy wide (or SLATE) if the live camera is unhealthy.
- **RESUME_AUTO is explicit, including after reconnect.** `on_speech_down()` and `on_reconnect()` both set an internal `auto_paused` flag; `on_speech_up()` alone does **not** clear it. Only an explicit `on_manual("RESUME_AUTO", ...)` releases the pause (and also bumps mode_revision). `on_reconnect()` additionally bumps mode_revision so any in-flight cues from before the reconnect are auto-rejected.
- **Missing/rejected ACK never changes `current_camera`.** `on_ack(decision_seq, applied=True)` commits `current_camera` and `last_cut_time`; `applied=False` leaves the state unchanged; an ACK for a `decision_seq` that no longer matches the pending slot is silently ignored.
- **`decision_seq` is monotonic across the session.** Every `on_cue()` and `on_manual()` issues one `SessionDecision` with `decision_seq = 1, 2, 3, ...` regardless of AI/manual origin.

## Rules encoded in `SemanticQueue` (from plan §5)

- **One active request + latest pending.** `submit(utterance, mode_revision, now)` places the utterance into `_in_flight` if empty, otherwise into `_pending`, replacing any older pending entry. Every replaced pending is appended to `dropped` with `reason: "superseded_by_newer_pending"`, its submitted-at timestamp, and the drop timestamp.
- **Bounded retries.** No retry logic. A parse exception or a queue-level timeout produces a safe HOLD cue with `action=HOLD`, `temporal_intent=UNCERTAIN`, `target_guest_ids=[]`, and the utterance in `evidence_text`. The queue advances (pending → in-flight) either way.
- **mode_revision provenance.** Whichever `mode_revision` the caller passed to `submit()` is set on the returned `Cue.mode_revision` field, whether the parse succeeded or errored.

## Contracts proposal updates

Added under `docs/contracts-proposal/`:

- `cue.schema.json` — added `mode_revision` (integer, default 0) as an optional field.
- `decision.schema.json` — added `decision_seq` (integer ≥ 1) and `mode_revision` (integer ≥ 0) as required fields; docstring explains the ACK protocol and the stale-cue rejection rule; a fifth fixture `stay_stale_mode_revision` is included.
- `decision_record.schema.json` (new) — shape of one line in the append-only decision log. Fields: `at`, `decision_seq`, `mode_revision`, `action`, `camera_id`, `reason`, plus optional `transcript_span`, `cue_summary`, `cameras_considered` (with `rejection_reason`), `latencies_ms`, `source`. Four fixtures included covering the fixture timeline.

## Tests added

`apps/api/tests/test_session.py` (20 cases): decision-seq monotonicity; mode_revision bumping on manual; stale-mode cue rejection; late cue after HOLD dropped; manual HOLD / TAKE / RESUME_AUTO / SLATE surfaces; TAKE requires camera id; unknown manual raises; ACK applied=True commits, applied=False leaves state, stale-seq ACK ignored; speech_down blocks auto but manual TAKE still works; speech_up alone doesn't resume; RESUME_AUTO re-enables takes; reconnect pauses + bumps mode; unhealthy-current failover during HOLD; SessionDecision shape.

`apps/api/tests/test_queue.py` (13 cases): first submit populates in-flight only; second goes to pending; third drops older pending and logs it; many submits leave only the latest pending; drain returns None when empty; drain returns cue with evidence_text from utterance; drain promotes pending; mode_revision captured at submit; per-entry (not global) mode_revision; queue-level timeout → safe HOLD without calling parse_fn; TimeoutError from parse → safe HOLD; generic exception → safe HOLD; `to_summary`; `clear` preserves the dropped log.

`apps/api/tests/test_log.py` (7 cases): one-line JSON append; multi-append order preserved; transcript_span + cue_summary populated; cameras_considered serialised with rejection reasons; latencies + source override; nested directory created; no chain-of-thought / logits fields present.

## Verified before commit

```
cd apps/api && python -m pytest -q      # 92 passed (52 + 40 new)
cd apps/api && python -m ruff check .   # All checks passed!
python scripts/fixture_cues.py          # 7 fixture lines, all "source": "FIXTURE"
```

The scripted timeline reproduces exactly:

```
1. seq= 1  rev=0  STAY   cam=CAM-HOST   reason=temporal_intent=FUTURE, not NOW
2. seq= 2  rev=0  TAKE   cam=CAM-GUEST  reason=role_based: sarah -> CAM-GUEST
3. seq= 3  rev=0  TAKE   cam=CAM-WIDE   reason=target sarah unusable -> wide; current unhealthy, safety failover
4. seq= 4  rev=1  STAY   cam=CAM-WIDE   reason=manual HOLD
5. seq= 5  rev=1  STAY   cam=CAM-WIDE   reason=cue from stale mode_revision 0 (current 1)
6. seq= 6  rev=2  STAY   cam=CAM-WIDE   reason=manual RESUME_AUTO
7. seq= 7  rev=2  TAKE   cam=CAM-GUEST  reason=role_based: daniel -> CAM-GUEST
```

## Known open items (for A/B/D)

- **`SessionDecision` is dataclass-native, not pydantic**, to match the existing `Decision` shape in `director.py`. If A prefers everything crossing the control WS to be pydantic, I'll wrap it — cost is one file.
- **`Cue.mode_revision` is new.** Extends the parser schema with a default-0 optional field, so old callers still work. If A rejects widening `Cue`, I'll move the tag onto a side-envelope in the queue.
- **`on_ack` currently ignores the `now` argument** for `applied=False` (it only updates state on `applied=True`). If A wants me to record the ACK time even for rejects, that's a small addition to `State`.
- **`fixture_cues.py` timing is scripted, not wall-clock.** Real live latency numbers still wait on the OpenAI + Deepgram integration on the release path.
