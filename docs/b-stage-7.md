# B — Stage 7

Plan §7, Stage 7 (B): *"reframe guest camera, re-enrol after memory-clearing
restart, check unknown rejection in current lighting."*

Exit gate: *"claims match today's conditions. If a capability fails, disable/disclose
it and update the saved submission."*

Branch: `codex/b-stage-7`, on top of Stage 7 prep.

Two of B's three checks need a camera and a person. **One half of the third does
not, and that half was executed for real.** The record separates them, because "we
checked the mechanism" and "we checked it with a person in front of a camera" are
different claims and only one of them was made.

| Check | Status |
|---|---|
| Guest-camera reframe invalidates identity | **NOT RUN** |
| Re-enrol after memory-clearing restart | **PARTIAL** — restart half verified live, re-enrol half NOT RUN |
| Unknown rejection in current lighting | **NOT RUN** |

Recorded in [`docs/results/b-stage-7-morning-check.md`](results/b-stage-7-morning-check.md).

## What was actually verified: a restart really does clear memory

B has claimed since Stage 0 that the backend is memory-only, so a restart destroys
every embedding. That was a design assertion. It is now demonstrated, against a live
server with the real ONNX models loaded.

Enrolled a guest, then stopped the process and started it again:

| | Before | After |
|---|---|---|
| Gallery version | 2 | **0** |
| Gallery entries | 1 (1 embedding) | **0** |
| Guest records | `[('guest-sarah', 'ACTIVE', 1)]` | **`[]`** |

Not "marked withdrawn" — **gone**. And the guest cannot be quietly revived:

```
POST /api/v1/guests/guest-sarah/references  ->  422
```

So re-enrolment genuinely means a fresh consent conversation, not a reattached
reference. That is the privacy default working, and it is the one Stage 7 check that
did not need hardware.

## One finding worth knowing before 08:00

**The gate's "today" is the machine's local date, not UTC.** Recording the check on
this machine produced `validatedOn: 2026-09-19` while UTC had already rolled to the
20th.

Local is the right choice — "this morning's lighting" is a local-time idea and the
team is in one room. But if somebody records a check on a laptop whose clock or
timezone disagrees with the room, the validation carries a different date and the
gate treats it as stale. **The symptom is a `not today` blocking reason on a check
that was just run**, which would be baffling at 08:40 without this note.

## The exit gate, item by item

- **Claims match today's conditions** — yes, trivially. B claims no identity
  capability, and the gate reports `ROLE_BASED` with five reasons including the
  absence of today's validation. There is no claim for today's conditions to
  contradict.
- **A capability failed** — no. None was exercised. `NOT_RUN` is recorded as distinct
  from `FAILED`, because "we did not try" and "we tried and it broke" are different
  facts, and Stage 7 prep made the gate treat them differently.
- **Update the saved submission** — done, and this is the part that had real content:

  `b-limitations-and-licences.md` now states that the gate **re-validates daily** —
  that even with every other piece of evidence in place, naming stays off until
  today's three checks are recorded, and that a failing check switches naming off on
  its own rather than relying on somebody remembering. It also upgrades the
  memory-only claim from asserted to **demonstrated**, with the restart evidence
  above.

  The freeze tests still pass, so the document and the code still agree.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q      ->  711 passed, 13 skipped
cd apps/api && python -m ruff check .   ->  All checks passed
restart clears the gallery and records  ->  2 entries -> 0, records -> []
reference to a vanished guest           ->  422
morning-check, all three NOT_RUN        ->  exit 1
readiness after restart                 ->  ROLE_BASED, 5 reasons
```

## What this does NOT establish

**No camera was involved, no person was present, nothing ran on D's Mac.** The
reference used in the restart test came from a drawn image file, and no consent was
recorded because there was nobody to record it from.

**Unknown rejection remains completely untested** — the check that matters most and
the one the exit gate is written around. Until it runs in the actual lighting, B's
position is unchanged and correct:

> `ROLE_BASED`. Cameras are chosen by role. No name on screen comes from a face.
> Checkable at `GET /api/v1/guests/readiness`.

If somebody runs the checks, the command is in
[b-stage-6-prep.md](b-stage-6-prep.md) and the result belongs in
`docs/results/b-morning-check.json`. **If unknown rejection fails, the gate drops to
`ROLE_BASED` by itself** — which is the whole reason it was built as a recorded
verdict rather than a note.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md),
[b-stage-5-prep.md](b-stage-5-prep.md), [b-stage-5.md](b-stage-5.md),
[b-stage-6-prep.md](b-stage-6-prep.md), [b-stage-6.md](b-stage-6.md),
[b-stage-7-prep.md](b-stage-7-prep.md).
