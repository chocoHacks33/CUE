# Cross-language contract fixtures

These files are the shared source of truth for Person B's vision and consent
vocabulary. The same bytes are validated by:

- `packages/contracts/src/guests.test.ts` (rules, on inline equivalents)
- `apps/web/src/guests/guestContract.test.ts` (observation fixture bytes)
- `apps/web/src/guests/consentFixtures.test.ts` (consent fixture bytes)
- `apps/api/tests/test_guest_contracts.py` (Python, pydantic models)
- `apps/api/tests/test_guest_registry.py` (the registry that enforces consent)

If a field changes, change it here first and let every side fail.

## Observations

| File | What it pins |
|---|---|
| `visual-observation.confirmed.json` | A named guest, confirmed, fresh, usable for a named take |
| `visual-observation.ambiguous.json` | An abstention: anonymous, no confidence, unusable |

## Consent lifecycle

| File | What it pins |
|---|---|
| `guest-enrolment-request.json` | A valid enrolment with full consent |
| `guest-enrolment-request.consent-refused.json` | Consent refused — schema-valid, and the registry must still refuse it |
| `guest-enrolment-request.recording-only.json` | Consented to filming but not to being matched by face |
| `guest-record.enrolling.json` | Enrolled, consenting, no references yet — not identifiable |
| `guest-record.json` | Active, three references, identifiable |
| `guest-record.withdrawn.json` | Consent withdrawn, references gone |
| `reference-submission.json` | One 128-d enrolment reference, deliberately not unit length |
| `purge-receipt.json` | What a deletion reports back |

The two refusal fixtures matter because the schema cannot express either rule:
both payloads validate against the contract and are rejected by the registry.
That boundary is the point — a type is not a consent policy.
