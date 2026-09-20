# B Stage 6 — overnight offline check

The record of running the handoff procedure. Stage 6 permits documentation and
offline regression checks and forbids new features, so this is what B did, and
filing the result is the whole point: at 08:00 somebody needs to know whether the
lane moved overnight without re-deriving what good looks like.

- Date/time: **2026-09-20 01:46 UTC**
- Commit checked: **`296e112`** (trunk, `codex/person-a-stage-0`, after #27 merged)
- Machine: B's Windows 11 laptop, Python 3.14.7
- Interpreter: `apps/api/.venv/Scripts/python.exe`
- Hardware used: **none.** No camera, no Mac, no network, no venue.

## `python scripts/b_offline_regression.py`

```
  PASS  B's tests      391 passed, 312 deselected, 2 warnings in 7.53s
  PASS  ruff           All checks passed!
  PASS  naming policy  ROLE_BASED True False
  PASS  doc links      16 documents, every link resolves

Nothing drifted. B's lane is where it was left.
```

Exit code **0**.

## Whole backend suite

```
cd apps/api && python -m pytest -q     ->  690 passed, 13 skipped
cd apps/api && python -m ruff check .  ->  All checks passed
```

**The 13 skips are not B's.** They are D's ffmpeg-dependent tests —
`test_av_skew.py` and `test_verify_recording.py` — skipping because `ffmpeg` is not
on this laptop's PATH. Verified with `pytest -rs`.

B's own model-backed tests **ran**, because the weights are present on this machine:

```
apps/api/models/face_detection_yunet_2023mar.onnx      232,589 bytes
apps/api/models/face_recognition_sface_2021dec.onnx 38,696,353 bytes
```

Worth stating explicitly, because "13 skipped" invites the assumption that B's
OpenCV tests were skipped. They were not.

Checked rather than assumed: with the weights temporarily moved aside, the suite
reads **677 passed, 26 skipped** — B's 13 model-backed tests join D's 13 ffmpeg
ones. That is the shape CI runs, and it is why CI being green does not by itself
mean the models were exercised.

## Readiness verdict, unchanged overnight

```json
{
  "namingPolicy": "ROLE_BASED",
  "roleBased": true,
  "unattendedNamingPermitted": false,
  "calibrationStatus": "PROVISIONAL_DEFAULT"
}
```

Four blocking reasons, the same four as at freeze: no identity report, no measured
calibration, no Mac runtime gate, no media checks.

## What was deliberately not done

Per Stage 6 and B's own handoff:

- No threshold retuned.
- The readiness gate was not loosened.
- No model migration; the pinned weights are untouched.
- No camera or Mac work — the venue is closed and such a fix would stay unverified.

## Outstanding, unchanged

All four are hardware and all four are for Stage 7 or later:

1. Mac runtime gate with D.
2. Real trials — 30 positives and 30 unknown/ambiguous.
3. A measured calibration.
4. B's media checks.

The Stage 7 command sequence is in [b-stage-6-prep.md](../b-stage-6-prep.md).
