# Cross-language contract fixtures

These files are the shared source of truth for Person B's vision vocabulary.
The same bytes are validated on both sides:

- `packages/contracts/src/vision.test.ts` (TypeScript, `parseVisualObservation`)
- `apps/api/tests/test_guest_contracts.py` (Python, pydantic models)

If a field changes, change it here first and let both sides fail.
