# B — Stage 7 prep

Plan §7, Stage 7 (B): *"reframe guest camera, re-enrol after memory-clearing
restart, check unknown rejection in current lighting."*

Exit gate: *"claims match today's conditions. **If a capability fails,
disable/disclose it** and update the saved submission."*

Branch: `codex/b-stage-7-prep`, on top of Stage 6.

All three of B's Stage 7 checks need hardware, and Stage 6 prep already wrote the
command sequence. What was missing was the machinery the **exit gate** depends on —
and there was a real gap.

## The gap

The readiness gate's four inputs — calibration, identity report, Mac gate, media
checks — all **accumulate**. Evidence goes in, capability comes out. Nothing could
express *"we re-tested this morning and it broke."*

So if unknown rejection failed at 08:30, there was no honest way to record it.
Somebody would have had to hand-edit an attestation, which means writing something
false into a file, to represent a true regression. That is exactly the shape of
mistake a tired person makes at 08:40 with a demo at 10:00.

`guests/morning_validation.py` is that channel.

## One rule: it can only take capability away

| Situation | Result |
|---|---|
| All three passed, **dated today** | grants nothing on its own; every other piece of evidence is still required |
| Any check **FAILED** | `ROLE_BASED` — naming switched off entirely, failure named with its date and who checked |
| **No** validation at all | no unattended naming; `NAMED_ASSIST` at best |
| Yesterday's passing validation | no unattended naming — moving a laptop changes framing |
| Partially run today | no unattended naming |

The load-bearing invariant, pinned by
`test_unattended_naming_requires_todays_complete_pass`: **unattended naming requires
today's complete pass.** Nothing else grants it, and four separate weakenings each
remove it.

### A failure and missing evidence are not the same thing

This is the distinction the module turns on, and `test_a_known_failure_is_treated_differently_from_missing_evidence`
pins it so nobody flattens it later:

- **FAILED** → `ROLE_BASED`. The suggestion itself is untrustworthy, and an operator
  cannot confirm their way out of that.
- **Not run** → `NAMED_ASSIST`. We do not *know* anything is broken; a human in the
  loop covers that, which is what ASSIST is for.

Collapsing the two would either over-block (treating "we didn't check" as a fault)
or under-block (treating a real regression as a gap in paperwork).

I got this wrong first time. My initial tests asserted `ROLE_BASED` for missing
evidence too; the implementation disagreed, and on thinking it through the
implementation was right. The tests were corrected, not the code — and the reasoning
is now recorded in the test itself rather than in my head.

A failure is also **not cleared by the clock**. Yesterday's failure still blocks
today; only a passing re-run clears it.

## Recording it at 08:30

```bash
cue-guests morning-check --by B \
  --re-enrolment PASSED --reframe PASSED --unknown-rejection PASSED \
  --note "overhead LEDs, blinds half open" \
  --out docs/results/b-morning-check.json
```

```
validated by: B
  PASSED   re-enrolment after the memory-clearing restart
  PASSED   guest-camera reframe invalidating identity
  PASSED   unknown rejection in this morning's lighting
verdict:      stands up for today; other evidence still required      exit 0
```

Note what it does **not** say: not "identity is ready". It stands up for today, and
that is all.

When unknown rejection fails — the case the exit gate is written for:

```
  FAILED   unknown rejection in this morning's lighting
verdict:      does NOT support a named policy today:
              - unknown rejection in this morning's lighting FAILED on 2026-09-20
                (checked by B)

A capability failed today. Leave identity naming off, disclose it, and update the
saved submission.                                                     exit 1
```

A partial run also exits 1, consistent with `evaluate` and `verify-cleanup`: a run
that did not establish its claim must not read as a green light. That was an
inconsistency in the first version of this command, caught by running it.

## It reaches the product

`GET /api/v1/guests/readiness` now carries `morningValidation` alongside the policy
and disclosure, so D's panel can show when the morning check was last done and what
it found — or that nobody has run it.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_morning_validation.py` | 21 |

Four existing tests changed, all deliberately. `NAMED_AUTO` now requires today's
validation, so the Stage 4 fixtures that reached it had to supply one, and the
no-evidence case now lists five blocking reasons instead of four. **This is a
tightening of a safety gate**, and it is the tightening the exit gate asks for.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  711 passed, 13 skipped
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
morning-check, all passed              ->  exit 0
morning-check, unknown rejection FAIL  ->  exit 1, names the failure
morning-check, partially run           ->  exit 1
```

## What this does NOT establish

**None of the three checks has been run.** They need a camera, a Mac and a person
who is not enrolled. This branch builds the channel that records the result and the
gate that honours it — it does not perform the validation.

B's readiness remains `ROLE_BASED`, now with a fifth blocking reason: no validation
against today's conditions. That is correct, and it will stay correct until someone
runs the checks at 08:00.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md),
[b-stage-5-prep.md](b-stage-5-prep.md), [b-stage-5.md](b-stage-5.md),
[b-stage-6-prep.md](b-stage-6-prep.md), [b-stage-6.md](b-stage-6.md).
