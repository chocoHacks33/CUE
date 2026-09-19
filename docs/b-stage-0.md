# Person B — Stage 0

Plan §7, Stage 0 (B): *"model-weight/licence check, consent roster and Mac
face-inference spike with D. Keep calibration and release captures separate."*

Branch: `codex/b-vision-clean` (PR #7).

## Deliverable 1 — model weight and licence check

| File | What it does |
|---|---|
| `apps/api/src/cue_api/vision/models.py` | Model registry: filenames, sources, licences, SHA-256 slots, `verify()` at load time |
| `apps/api/src/cue_api/vision/adapters/opencv_models.py` | YuNet detector + SFace embedder, OpenCV imported lazily. **Never executed** |
| `docs/vision-models.md` | Where the weights come from, their licences, and the pinning procedure |

**Checksums are deliberately empty.** A digest written from memory would pass
review and prove nothing, so `expected_sha256` stays unset and
`tests/test_vision_models.py` asserts that nothing is pinned until someone
downloads a file and records what they actually got. The doc and the code
cannot drift apart.

Weights are not committed; `models/` is gitignored.

## Deliverable 2 — consent roster

| File | What it does |
|---|---|
| `apps/api/src/cue_api/guests/registry.py` | Event-scoped, in-memory consent + reference registry with deletion receipts |
| `apps/api/src/cue_api/guests/contracts.py` | Consent purposes, guest status, enrolment rules (`GUEST_STATUSES`, `CONSENT_PURPOSES`) |
| `docs/guest-privacy.md` | What the code does today about consent, storage and deletion — not an intention |

Rules enforced, not just documented:

- Enrolment is refused without `consentGranted`, and refused if it omits the
  `LIVE_IDENTIFICATION` purpose — consenting to be filmed is not consenting to
  be matched by face.
- Withdrawal is a deletion, not a flag: references are destroyed and a
  `PurgeReceipt` reports the count. A withdrawn guest may not hold references
  and cannot be re-enrolled by adding one.
- References never leave memory and never reach a browser. The gallery route
  that carries embeddings is worker-only.

## Deliverable 3 — Mac face-inference spike with D

**NOT RUN.** Needs D's MacBook. Template:
`docs/results/b-identity-report.template.md`.

This is the Stage 0 exit gate for B's lane: install `apps/api[vision]` on the
Mac and confirm an OpenCV wheel exists for D's Python and architecture. Until
that passes, no calibration and no live matching work is justified — which is
why Stage 2/3 is off this branch entirely.

Calibration and release captures are kept separate, as the plan requires: no
calibration exists here at all, and every observation that carries a confidence
must declare `PROVISIONAL_DEFAULT` rather than implying a measured number.

## Tests

| File | Tests |
|---|---|
| `apps/api/tests/test_guest_registry.py` | 44 |
| `apps/api/tests/test_vision_models.py` | 6 |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  182 passed (whole backend suite)
cd apps/api && python -m ruff check .  ->  All checks passed
```

Never run: any real pixels. No weights downloaded, no OpenCV wheel installed,
no face detected. The adapters are written against OpenCV's documented API and
have never executed.

See also [b-prep-stage-1.md](b-prep-stage-1.md) and
[b-stage-1.md](b-stage-1.md).
