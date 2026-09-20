# B Stage 7 — morning re-validation

Stage 7 asks B for three checks against today's conditions: *"reframe guest camera,
re-enrol after memory-clearing restart, check unknown rejection in current
lighting."*

**Status: NOT RUN.** Two of the three need a camera and a person. One half of the
third was verified for real, and this page separates them carefully, because "we
checked the mechanism" and "we checked it with a person in front of a camera" are
different claims.

- Date/time: **2026-09-20 02:35 UTC** - local date on this machine is
  **2026-09-19**, which is what the gate compares against (see the note below)
- Commit: `f54eac8` (trunk, after #30 merged)
- Machine: B's Windows 11 laptop, Python 3.14.7
- Camera used: **none.** Mac used: **none.** Person present: **none.**

## The three checks

| Check | Status |
|---|---|
| Guest-camera reframe invalidates identity | **NOT RUN** — needs a camera to reframe |
| Re-enrol after memory-clearing restart | **PARTIAL** — the restart half verified; the re-enrol half NOT RUN |
| Unknown rejection in current lighting | **NOT RUN** — needs an unenrolled person and today's light |

Recorded through the tool rather than by hand:

```
cue-guests morning-check --by B \
  --re-enrolment NOT_RUN --reframe NOT_RUN --unknown-rejection NOT_RUN
```

```
validated on: 2026-09-19
validated by: B
  NOT_RUN  re-enrolment after the memory-clearing restart
  NOT_RUN  guest-camera reframe invalidating identity
  NOT_RUN  unknown rejection in this morning's lighting
verdict:      does NOT support a named policy today:
              - not re-checked against today's conditions: re-enrolment after the
                memory-clearing restart, guest-camera reframe invalidating
                identity, unknown rejection in this morning's lighting
```

and on stderr, with **exit 1**:

```
Not every check was run, so today's conditions are unconfirmed. Unattended naming
stays off until all three pass.
```

Exit 1 is correct. A run that established nothing must not read as a green light.

### "Today" is the machine's local date

The gate compares against local `date.today()`, not UTC. On this machine that is
2026-09-19 while UTC has already rolled to the 20th.

Local is the right choice - "this morning's lighting" is a local-time idea and the
team is in one room. But it is worth knowing before somebody records a check on a
laptop whose clock or timezone disagrees with the room: the validation would carry a
different date and the gate would treat it as stale. The symptom is a `not today`
blocking reason on a check that was just run.

## What *was* verified: the restart really does clear memory

This is the half of check 2 that needs no camera, and it was executed against a
live server with the real models.

**Before the restart** — a guest enrolled from a reference image:

```
gallery version: 2 | entries: 1
    guest-sarah embeddings: 1
guest records: [('guest-sarah', 'ACTIVE', 1)]
```

**After stopping the process and starting it again:**

```
gallery version: 0 | entries: 0
guest records: []
```

Not "marked withdrawn" — **gone**. No record, no embedding, gallery version back to
zero. And the guest cannot be quietly revived:

```
POST /api/v1/guests/guest-sarah/references  ->  422
```

Re-enrolment is genuinely required, which means a fresh consent conversation rather
than a reattached reference. That is the privacy default working as designed, and it
is now demonstrated rather than asserted.

Readiness immediately after the restart:

```
policy: ROLE_BASED | morningValidation: None | blockingReasons: 5
```

## What was NOT verified

- **Nobody was enrolled from a camera.** The reference above came from a drawn image
  file. No consent was recorded because no person was involved.
- **No reframe happened**, because there is no camera pointed at anything.
- **Unknown rejection is completely untested in today's light** — the check that
  matters most, and the one the exit gate is written around.
- **Nothing ran on D's Mac.**

## Exit gate

Stage 7's gate: *"claims match today's conditions. If a capability fails,
disable/disclose it and update the saved submission."*

- **Claims match today's conditions:** yes, and trivially so. B claims no identity
  capability, and the readiness gate reports `ROLE_BASED` with five reasons
  including the absence of today's validation. There is no claim that today's
  conditions could contradict.
- **A capability failed:** no — none was exercised. `NOT_RUN` is recorded as
  distinct from `FAILED`, because "we did not try" and "we tried and it broke" are
  different facts and the gate treats them differently.
- **Saved submission updated:** yes — `b-limitations-and-licences.md` now records
  that the gate re-validates daily and that no validation exists for today.

## If somebody runs the checks

```bash
cue-guests morning-check --by <name> \
  --re-enrolment PASSED --reframe PASSED --unknown-rejection PASSED \
  --note "<the lighting, who was present>" \
  --out docs/results/b-morning-check.json
```

It exits non-zero unless all three pass. **If unknown rejection fails, the gate
drops to `ROLE_BASED` on its own** — nobody has to remember to switch identity off,
which is the point of recording the failure rather than noting it.

Full sequence in [b-stage-6-prep.md](../b-stage-6-prep.md).
