# B — Stage 5 prep

Plan §7, Stage 5 (B): *"measured identity report, consented-data cleanup,
limitations and licences."*

Branch: `codex/b-stage-5-prep`, on top of Stage 4.

Stage 5 is freeze-and-capture. Two of B's three items are things you write and run
rather than measure, so they are done here. The third needs trials nobody has run.

| Item | State |
|---|---|
| Consented-data cleanup | **Done and run** — verified cleanup, executed against a live server |
| Limitations and licences | **Done** — submission-ready, with licences read rather than assumed |
| Measured identity report | **NOT RUN** — needs real people; the empty record is already filed |

## Cleanup that can prove itself

Two things already delete consented data, and **neither reads it back**:

- **A's `POST /api/v1/events/{id}/end`** — the authoritative end of an event. It
  purges guest records and observations *and* revokes control sessions, deletes
  grants, claims and bindings, and sets the mode to `ENDED`.
- **B's `DELETE /api/v1/guests`** — guest data alone, mid-event.

That gap is what this fills. **"We deleted it" and "we went back and checked it was
gone" are different claims**, and a purge that silently half-succeeded looks
identical to one that worked if nobody re-reads.

### It is called `verify-cleanup`, not `end-event`

A's endpoint landed on trunk while this branch was open, and it already purges
guest data. A B command called `end-event` would have been actively dangerous:
somebody runs it at the real event end, believes the event is ended, and leaves
sessions live, bindings in place and the mode not `ENDED`. So B's command verifies
by default and only purges when asked:

```bash
# normal: right after A's authoritative end, just prove it worked
cue-guests verify-cleanup --api … --event … --out docs/results/b-cleanup-record.json

# guest-only cleanup mid-event
cue-guests verify-cleanup --api … --event … --purge
```

Run against a live server, in the real order — enrol a guest, post an observation,
call A's end, then verify:

```
event:        hackmit-demo
purge:        not by this command — verifying only
verified:     worker gallery holds no embeddings
verified:     no guest records remain
verified:     no camera holds live evidence
verdict:      clean — re-read found nothing remaining          exit 0
```

And before anything was purged, the same command refuses:

```
verdict:      NOT CLEAN — consented data is still present:
              - worker gallery: guest-sarah still has 1 embedding(s)
              - guest record: guest-sarah still reports 1 reference(s)
              - guest record: guest-sarah still claims consent after the event ended
              - live evidence: CAM-GUEST still holds an observation     exit 1
```

It writes a filable record:

```json
{
  "eventId": "hackmit-demo",
  "guestsPurged": [],
  "referencesDeleted": 0,
  "observationsDropped": 0,
  "purgedAtMs": 0,
  "purgedHere": false,
  "clean": true,
  "verificationComplete": true,
  "checksRun": ["gallery", "guest_records", "live_evidence"],
  "verified": ["worker gallery holds no embeddings", "no guest records remain",
               "no camera holds live evidence"],
  "remaining": []
}
```

The zeros are correct and deliberate: this run verified somebody else's deletion, so
it reports no deletions of its own rather than taking credit for A's. A test pins
that (`test_a_verify_only_record_does_not_claim_deletions_it_did_not_make`).

### Three places data could survive, all re-read

| Check | What would be a finding |
|---|---|
| Worker gallery | any guest still holding an embedding — this is the only route embeddings leave by |
| Guest records | any record still reporting a reference count, or still claiming consent after the event ended |
| Live evidence | any camera still holding an observation |

A withdrawn stub with nothing attached is acceptable: the *record* of a withdrawal
may remain, what it must not hold is data.

### It cannot be clean by accident

The first version had a real flaw, found by writing a test for it: a
`CleanupRecord` with **no checks run** reported `clean: true`, because nothing was
remaining. That is precisely the failure the module exists to prevent — an
unverified record indistinguishable from a verified one.

`clean` now requires that **every** required check actually ran, tracked in
`checks_run`. A partial verification reports:

```
verdict:      UNVERIFIED — these checks never ran: live_evidence
```

And the command exits non-zero on anything other than a verified-clean result,
because a cleanup nobody verified is indistinguishable from a cleanup that did not
happen. A verify-only failure says "consented data is still present" rather than
"survived the purge", because this run did not purge anything and should not imply
it did.

### The receipt is not the evidence

`test_a_receipt_claiming_deletions_does_not_make_a_run_clean` drives a backend that
reports 99 deletions and then still has the embedding. The receipt is the backend's
word about itself; the re-read is the evidence. Only the second decides the verdict.

## Limitations and licences

[`docs/b-limitations-and-licences.md`](b-limitations-and-licences.md) is written to
be read by a sceptical judge, which is the correct posture. It states in one
paragraph that **identity naming is currently switched off** and points at
`GET /api/v1/guests/readiness` so the claim can be checked rather than trusted.

- **Licences read, not assumed.** Both model `LICENSE` files were fetched from
  upstream and read: YuNet is MIT (© 2020 Shiqi Yu), SFace is Apache-2.0. Both
  digests were hashed locally, and YuNet's matches upstream's git-lfs `oid`.
- **Dependency licences read from installed package metadata**, with real versions,
  rather than copied from a requirements file. numpy's is the compound
  `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`, which is what its metadata
  actually says.
- A "what is NOT done" section listing fourteen real gaps, and an explicit list of
  what will and will not be said on stage.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_cleanup.py` | 20 |

The ones that matter drive a backend that **lies by omission** — reporting a
successful purge while still holding an embedding, a reference count, or live
evidence — and check the record catches it.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  617 passed
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
verify-cleanup before any purge        ->  NOT CLEAN, 4 findings, exit 1
A's /events/{id}/end, then verify      ->  clean, exit 0, record written
```

That 617 is the whole backend suite, and it grew because A's and C's Stage 3
integration merged into trunk while this branch was open. B owns 365, of which 20
are new here.

## What this does NOT establish

**The measured identity report still does not exist**, and this branch does not
pretend otherwise. `docs/results/b-identity-report.md` records 0 trials in both
arms, and the readiness gate consequently still reports `ROLE_BASED`.

The cleanup verification ran against a **local server with a drawn face and no real
person**. It proves the purge-and-re-read logic works. It is not the
consented-data cleanup of a real event, because there has not been one.

Still needed, all hardware:

1. Mac runtime gate with D.
2. Real trials — 30 positives and 30 unknown/ambiguous
   ([b-stage-3.md](b-stage-3.md) has the commands).
3. A measured calibration.
4. B's media checks.

At the real event end: call A's `POST /api/v1/events/{id}/end`, then
`cue-guests verify-cleanup --out docs/results/b-cleanup-record.json` to file the
evidence that consented data was actually destroyed.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md).
