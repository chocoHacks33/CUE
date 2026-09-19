# Person B — Stage 1 prep

The offline half of Stage 1: the contracts and fixtures that can be written and
tested before any camera or model exists. Same shape as C's Stage 1 prep
(`apps/api/src/cue_api/speech/` with its Deepgram fixtures) — pure logic, driven
by fixture bytes, no hardware.

Branch: `codex/b-vision-clean` (PR #7).

## What it is

One vocabulary for guest identity, defined once and validated identically in
both languages, so a field change breaks both sides at the same time instead of
drifting.

| File | What it does |
|---|---|
| `packages/contracts/src/vision.ts` | TypeScript types + runtime parsers: observation, guest, consent, enrolment, purge |
| `apps/api/src/cue_api/guests/contracts.py` | Pydantic mirror, same rules, strict (unknown fields rejected) |
| `packages/contracts/fixtures/` | The shared bytes both sides validate |

## The fixtures

| File | What it pins |
|---|---|
| `visual-observation.confirmed.json` | A named guest, confirmed, fresh, usable for a named take |
| `visual-observation.ambiguous.json` | An abstention: anonymous, no confidence, unusable |
| `guest-enrolment-request.json` | A valid enrolment with full consent |
| `guest-enrolment-request.consent-refused.json` | Consent refused — schema-valid, and the registry must still refuse it |
| `guest-enrolment-request.recording-only.json` | Consented to filming but not to being matched by face |
| `guest-record.enrolling.json` | Enrolled, consenting, no references yet — not identifiable |
| `guest-record.json` | Active, three references, identifiable |
| `guest-record.withdrawn.json` | Consent withdrawn, references gone |
| `reference-submission.json` | One 128-d enrolment reference, deliberately not unit length |
| `purge-receipt.json` | What a deletion reports back |

The two refusal fixtures are the point: **both validate against the schema and
are still rejected by the registry.** A type is not a consent policy, and
keeping fixtures for the gap stops anyone assuming validation is authorisation.

## Rules the contract enforces

- An `UNKNOWN` or `AMBIGUOUS` observation may not carry a name.
- Only a `CONFIRMED` observation can support a named take.
- A display name without a guest ID is a seat label, not an identity.
- An uncalibrated match may not report a calibrated confidence.
- An observation cannot expire before it was observed.
- A guest record may never carry embeddings.
- A withdrawn guest must record the withdrawal, drop consent, and hold no
  references.

## Fields that exist but nothing populates yet

`calibrationStatus`, `calibratedConfidence`, `margin`, `similarity`,
`runnerUpGuestId`, `consecutiveConfirmations`, `trackKey`, `pipelineVersion`.

These are contract surface for Stage 2/3. They are defined here on purpose — the
contract is the thing Stage 1 prep delivers — but **no code on this branch
produces an observation**, so C should treat the observation half as
contract-only for now. `calibratedConfidence` can only ever be
`PROVISIONAL_DEFAULT` until Stage 3 fits a real calibration.

## Tests

| File | Tests |
|---|---|
| `apps/api/tests/test_guest_contracts.py` | 26 |
| `apps/web/src/guests/visionContract.test.ts` | fixture parsing + named-take gate |
| `apps/web/src/guests/consentFixtures.test.ts` | consent, enrolment, reference and purge fixtures |
| `packages/contracts/src/vision.test.ts` | the rules, on inline equivalents |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  182 passed (whole backend suite)
cd apps/api && python -m ruff check .  ->  All checks passed
```

**Not run locally:** `npm ci / typecheck / test / build`. Node is not installed
on this machine, so the three TypeScript suites above rest on CI. CI passes on
macOS and Windows for PR #7.

See also [b-stage-0.md](b-stage-0.md) and
[b-stage-1.md](b-stage-1.md).
