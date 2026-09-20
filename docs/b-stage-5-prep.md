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

Deleting was already implemented and tested: `DELETE /api/v1/guests` purges an
event and returns a receipt counting what went. The half that was missing is the
one a guest is actually owed.

**"We deleted it" and "we went back and checked it was gone" are different
claims.** A purge that silently half-succeeded looks identical to one that worked,
if nobody re-reads. So `cue-guests end-event` purges, then reads the event back
through the same public routes and states what it found:

```
event:        hackmit-demo
guests:       1 purged
references:   1 deleted
observations: 1 dropped
verified:     worker gallery holds no embeddings
verified:     no guest records remain
verified:     no camera holds live evidence
verdict:      clean — re-read found nothing remaining
```

That is a real run against a live server, after enrolling a guest and posting an
observation so there was something to clean. It writes a filable record:

```json
{
  "eventId": "hackmit-demo",
  "guestsPurged": ["guest-sarah"],
  "referencesDeleted": 1,
  "observationsDropped": 1,
  "clean": true,
  "verificationComplete": true,
  "checksRun": ["gallery", "guest_records", "live_evidence"],
  "verified": ["worker gallery holds no embeddings", "no guest records remain",
               "no camera holds live evidence"],
  "remaining": []
}
```

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
happen.

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
| `tests/test_guest_cleanup.py` | 16 |

The ones that matter drive a backend that **lies by omission** — reporting a
successful purge while still holding an embedding, a reference count, or live
evidence — and check the record catches it.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  574 passed
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
cue-guests end-event (live server)     ->  clean, exit 0, record written
```

That 574 is the whole backend suite; B owns 361, of which 16 are new here.

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

At the real event end, `cue-guests end-event --out docs/results/b-cleanup-record.json`
files the evidence that consented data was destroyed.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md).
