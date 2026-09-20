# B — Stage 5

Plan §7, Stage 5 (B): *"measured identity report, consented-data cleanup,
limitations and licences."*

Branch: `codex/b-stage-5`, on top of Stage 5 prep.

**Two of the three items were finished in prep, and the third is a measurement I
cannot perform.** So this branch does not add a third deliverable to look busy. It
does the two things a freeze stage actually needs once the artefacts exist: make
the freeze enforceable, and make the run sheet usable.

| Item | State |
|---|---|
| Consented-data cleanup | **Done and run** in prep — verified, against a live server |
| Limitations and licences | **Done** in prep — submission-ready |
| Measured identity report | **NOT RUN** — needs real people on D's Mac |

## A freeze nobody enforces is not a freeze

`docs/b-limitations-and-licences.md` is what a judge reads. It states model
digests, licences, thresholds and the current naming policy **as facts**. Every one
of those can be made false by a one-line change elsewhere — silently — and the
document would go on claiming it. That is the realistic failure mode of a Sunday
morning, not a hypothetical one.

`tests/test_guest_submission_claims.py` **reads the document** and compares what it
says with what the code does:

| Claim in the document | Checked against |
|---|---|
| Both model digests | `expected_sha256` in `face_models.py` |
| No digest quoted that nothing pins | the pinned set — a digest nothing verifies is worse than none |
| Model filenames and licences, per table row | the model registry |
| Accept 0.363, margin 0.06, 3 confirmations, 1.2 s window, 1.5 s TTL | `MatchThresholds` and `DEFAULT_IDENTITY_TTL_MS` |
| 0.363 is an anchor, not our result | `SFACE_COSINE_REFERENCE` |
| "identity naming is switched off" | `assess_identity_readiness` with no evidence |
| "check it at `GET /api/v1/guests/readiness`" | the route exists in the OpenAPI schema |
| "No real human face has ever been through this system" | still present in the document |
| No accuracy percentage anywhere in the file | a regex over the whole document |

The tests parse the markdown rather than restating the numbers. A test that
hard-codes `0.363` twice proves only that I can copy, and would keep passing while
the document told a judge something untrue.

### It bites

Verified by breaking it on purpose — changing `margin` from `0.06` to `0.09`:

```
FAILED test_the_thresholds_the_document_quotes_are_the_thresholds_in_force
  assert '0.09' in "- **Thresholds are unmeasured.** Accept similarity 0.363,
                    margin 0.06, 3 confirmations in 1.2 s, 1.5 s identity TTL…"
```

It names exactly what disagrees. Restored, and back to passing.

One test is deliberately a tripwire rather than an invariant:
`test_the_identity_report_on_disk_still_records_no_trials`. If somebody runs the
trials and fills the report in, that test fails **on purpose** — the readiness
claim, the disclosure and these freeze tests all have to be revisited together, not
one at a time.

## A run sheet that survives 11pm

[`b-run-sheet.md`](b-run-sheet.md) is one page, written to be used rather than read
in advance:

1. Check the readiness endpoint first, and **say the `disclosure` field** — do not
   improvise around it.
2. The answer to "does the face recognition work?" — *"We built it and we have not
   measured it, so it is switched off. You can check that on the readiness
   endpoint."* That is a better answer than a number nobody verified.
3. What not to say.
4. Enrolment, only with recorded spoken consent; the CLI refuses without
   `--consent-confirmed`.
5. **Withdrawal, as one command**, with a receipt to show the guest.
6. End of event: A's `/events/{id}/end` first, then `verify-cleanup` to prove it.
7. A symptom table, including the 131-byte git-lfs pointer that fails to parse as
   ONNX, and the unnormalised-embedding failure that makes every face match
   everybody.

Every command in it was checked to exist, and `--consent-confirmed` was checked to
be enforced rather than decorative.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_submission_claims.py` | 14 |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  631 passed
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
margin 0.06 -> 0.09 (deliberate)       ->  freeze test fails and names the mismatch
```

That 631 is the whole backend suite; B owns 379, of which 14 are new here.

## What this does NOT establish

**The measured identity report still does not exist.** That is Stage 5's first item
and the only one outstanding, and no amount of code produces it — it needs real
people in front of real cameras on D's Mac.

What this branch guarantees is narrower and worth having: **if the submission
document and the code ever disagree, CI says so before a judge does.**

Outstanding, all hardware, in order:

1. Mac runtime gate with D.
2. Real trials — 30 positives and 30 unknown/ambiguous, seats, angles and lighting
   varied ([b-stage-3.md](b-stage-3.md) has the commands).
3. A measured calibration.
4. B's media checks.

If none of that happens, B ships `ROLE_BASED` with its disclosure, which is what
the plan's H10 rule prescribes and what the run sheet is written around.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md),
[b-stage-5-prep.md](b-stage-5-prep.md).
