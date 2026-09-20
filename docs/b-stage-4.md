# B — Stage 4

Plan §7, Stage 4 (B): *"positive and unknown/ambiguous identity trials; change
seats, angles and lighting; consent/deletion test."*

Exit gate: *"choose named AUTO only if evidence supports it. At H10, unreliable
wrong-person rejection means **disclosed** operator-confirmed/role-based ASSIST."*

Branch: `codex/b-stage-4`, on top of Stage 4 prep.

**Say it plainly: Stage 4's trials have not been run, and no code can run them.**
They need real people in front of real cameras on D's Mac. What this branch does is
finish the two parts that are not measurement — make the exit gate's verdict
reachable by the product, and put the missing trials on the record — and then stop,
rather than manufacture activity that looks like progress.

## Status of the three items

| Item | State |
|---|---|
| Consent/deletion test | **Done** — shipped in Stage 4 prep, driven through the HTTP API |
| Change seats, angles and lighting | **Offline half done** — the capture envelope is swept and the seat/camera rules are tested. The camera trials themselves: NOT RUN |
| Positive and unknown/ambiguous identity trials | **NOT RUN** — needs the Mac and real people |

## Disclosure has to reach the product

The gate says the fallback must be *disclosed*. Stage 4 prep computed the verdict,
but nothing consumed it, and a disclosure that exists only in a document is not
disclosed to anyone watching the show. So it is now an endpoint:

```
GET /api/v1/guests/readiness?eventId=…
```

```json
{
  "guestContractVersion": "0.1.0",
  "eventId": "hackmit-demo",
  "namingPolicy": "ROLE_BASED",
  "roleBased": true,
  "unattendedNamingPermitted": false,
  "calibrationStatus": "PROVISIONAL_DEFAULT",
  "disclosure": "Cameras are chosen by role, not by face recognition. Nothing on screen is identified by face.",
  "blockingReasons": [
    "no identity report exists, so nothing is known about wrong-person rejection",
    "the calibration is PROVISIONAL_DEFAULT, so any confidence shown is an anchor rather than a measurement",
    "the Mac runtime gate has not passed",
    "B's media checks have not run"
  ],
  "attestations": {}
}
```

That is the real response from the running app today, not an illustration. D reads
`disclosure`; C passes `roleBased` to the director.

It is **computed per request, never cached**. A calibration can be dropped in
mid-event, and a stale `"AUTO"` is the single worst thing this endpoint could serve.

### The TypeScript parser refuses contradictions

`parseIdentityReadiness` rejects a payload that would render as a reassuring
impossibility: `ROLE_BASED` that does not set `roleBased`, unattended naming
outside `NAMED_AUTO`, `NAMED_AUTO` that does not permit it, or an **empty
disclosure**. A readiness with nothing to disclose cannot be shown to an audience,
so it is refused at the boundary rather than displayed as a blank.

A Python test asserts the route never emits those combinations, and the TS tests
assert the parser rejects them. Both sides, because this is the field that protects
the audience.

## Attestations are not bare booleans

Two of the gate's four inputs cannot be verified by code: whether the Mac runtime
gate passed, and whether B's media checks ran. Those are human claims, and an
unverifiable claim that flips a safety gate should be awkward to assert.

So an `Attestation` must name **who** ran the check and **which results document**
backs it. A flag nobody signed is not evidence, and a claim pointing at nothing to
read cannot be checked afterwards. Both are refused at construction:

```
AttestationError: An attestation must name who ran the check
AttestationError: An attestation must name the results document that backs it;
                  a claim with nothing to read is not evidence
```

The endpoint echoes who signed what, so the producer panel can show it.

## The trials, on the record

B previously had only templates in `docs/results/` while other lanes had filled
records. Both are now filled in — as **NOT RUN**, which is the honest content:

- **[`docs/results/b-identity-report.md`](results/b-identity-report.md)** — every
  trial count is 0. It separates the five invalidation behaviours that *are*
  covered by automated fixture tests from the camera trials that are not, because
  conflating those two is how a suite of green tests becomes a claim about people.
  It also records why drawn faces cannot substitute: measured here, every
  detectable drawn variant scored 0.78–0.93 cosine against an unrelated reference.
- **[`docs/results/b-media-check.md`](results/b-media-check.md)** — Test 4 is the
  only one with partial results, and every row states **which machine** it ran on,
  because "OpenCV works" on Windows is not the claim the test is asking for.

Both name what will be claimed on stage and what will not.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_readiness_route.py` | 12 |
| `packages/contracts/src/guests.test.ts` | 9 added for the readiness parser |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  558 passed
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
GET /api/v1/guests/readiness           ->  200, ROLE_BASED with four reasons
```

That 558 is the whole backend suite; B owns 345, of which 12 are new here.

**Not run locally:** the npm gates. Node is not installed on this machine, and this
branch adds TypeScript, so the 9 parser tests rest on CI. **Confirm from the CI
result before merging.**

## What this does NOT establish

**Nothing about accuracy, and nothing about hardware.** The endpoint reports the
absence of evidence correctly; it does not create any.

The honest position, which is also B's shipping position unless the trials happen:

> The readiness gate returns `ROLE_BASED`. Cameras are chosen by role. No name on
> screen comes from a face. Anyone can check that live at
> `GET /api/v1/guests/readiness`.

That is a defensible demo rather than a broken one, and it is exactly what the
plan's H10 rule asks for. Moving off it needs, in order:

1. **Mac runtime gate with D** — `pip install -e "apps/api[opencv]"` on the MacBook.
2. **Real trials** — 30 positives and 30 unknown/ambiguous, seats, angles and
   lighting varied. `cue-guests trials` scores them,
   `cue-guests evaluate` judges them and exits non-zero while they do not support a
   claim.
3. **A measured calibration** — `cue-guests calibrate` on two-sided held-out pairs.
4. **B's media checks** — the four tests in
   [`b-media-check.md`](results/b-media-check.md).

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md).
