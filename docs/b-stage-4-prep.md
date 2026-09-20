# B — Stage 4 prep

Plan §7, Stage 4 (B): *"positive and unknown/ambiguous identity trials; change
seats, angles and lighting; consent/deletion test."*

Exit gate: *"choose named AUTO only if evidence supports it. At H10, unreliable
wrong-person rejection means disclosed operator-confirmed/role-based ASSIST."*

Branch: `codex/b-stage-4-prep`, on top of Stage 3.

Stage 4 is a failure-testing stage, so most of it is trials on hardware. The
prep-able part is the piece that decides **what the trials are allowed to
authorise** — and, as with Stage 3 prep, writing that before the numbers exist is
the only way the judgement stays honest.

## What it adds

| File | What it does |
|---|---|
| `guests/identity_readiness.py` | The exit gate: may a name come from a face, and may it air unattended? |
| `tests/test_guest_consent_deletion.py` | Stage 4's consent/deletion test, through the real routes |
| `tests/test_guest_capture_conditions.py` | Where the capture gate starts refusing: lighting, blur, distance, framing |

## The exit gate, made executable

`assess_identity_readiness()` answers one narrow question from evidence, and
hands the result to machinery that already exists. It deliberately does **not**
decide the show's mode: `ControlMode` is A's, the director's `Mode` is C's. B owns
identity, so B owns only this.

| Policy | Meaning | `role_based` |
|---|---|---|
| `NAMED_AUTO` | identity may name a guest with nobody in the loop | `False` |
| `NAMED_ASSIST` | identity may *suggest*; an operator confirms before air | `False` |
| `ROLE_BASED` | no name comes from a face; cameras still chosen by role | `True` |

That `role_based` value is not a new vocabulary — it is the keyword
`policy.director.decide()` already takes to skip the identity check and name from
the roster instead. A test asserts the signature still matches, so the two cannot
drift apart.

### It fails closed

Reaching `NAMED_AUTO` requires **all four**, and any missing one is named in
`blocking_reasons`:

1. an identity report that is claimable at all — 30 trials per arm, zero wrong names
2. a `MEASURED` calibration, not the provisional anchor
3. the Mac runtime gate passed
4. B's media checks passed

**Where the project actually stands today**, with no evidence at all:

```
naming policy:  ROLE_BASED
role_based:     True
unattended:     False
disclose:       Cameras are chosen by role, not by face recognition. Nothing on
                screen is identified by face.
why not more:
                - no identity report exists, so nothing is known about
                  wrong-person rejection
                - the calibration is PROVISIONAL_DEFAULT, so any confidence shown
                  is an anchor rather than a measurement
                - the Mac runtime gate has not passed
                - B's media checks have not run
```

### A wrong name is disqualifying, not a deduction

One wrong name drops **straight to `ROLE_BASED`**, skipping `NAMED_ASSIST`
entirely. That is deliberate and worth being explicit about, because "operator
confirms" sounds like a safety net and here it is not one: an operator cannot
confirm their way out of a system that sometimes offers the wrong person
confidently. The suggestion is the thing that is wrong, and a confident wrong
suggestion is exactly what a tired operator accepts.

A **miss** is treated differently — failing to name an enrolled guest costs the
completion rate and does not block a claim. Conflating the two is what leads to
loosening a threshold to rescue a miss.

### The disclosure is never empty

Every policy carries a sentence the demo must say out loud, including the
permissive one. There is no state in which identity is used and nothing is
disclosed.

## The consent/deletion test

Stage 4 names this explicitly, and it is the scenario that matters if somebody
asks the uncomfortable question on the night. It runs through the **HTTP API**,
not the registry, so it covers the paths an operator would actually use.

A guest consents, is enrolled, is recognised live, then withdraws. Afterwards:

- gone from the worker gallery
- gone from live evidence on every camera
- listed only as `WITHDRAWN`, consent `granted: false`, `referenceCount: 0`
- the receipt counts what was deleted, so deletion is observable rather than promised
- **a late observation already in flight is refused with 409** and cannot resurrect
  the name
- re-adding a reference is refused **403** — withdrawal is not a pause button, and
  re-enrolment means a fresh consent conversation
- other guests and other events are untouched
- no deletion endpoint works without the operator credential, and a refused
  request is not a silent deletion

## The capture envelope

Seats and cameras were already covered by the pipeline tests — an old seat loses
its name, and identity never follows a guest to another camera. What was missing
is *where the gate starts refusing*, so a real capture can later be compared
against a written expectation instead of a guess:

| Condition | Usable |
|---|---|
| Brightness | 0.20 – 0.92; below is `underexposed`, above is `overexposed` |
| Sharpness | ≥ 0.25; below is refused rather than matched weakly |
| Face width | ≥ 0.08 of frame width (≈103 px at 1280), so it survives a resolution change |
| Framing | any clipping at the frame edge is refused |
| Detector score | ≥ 0.70, which is usually an angle the model cannot read |

Two properties worth naming: a refusal says **which way** it failed, because "too
dark" and "blown out" need opposite fixes; and conditions that each pass alone
still pass together, so the gate does not reject a frame merely for sitting near
several edges.

**Every number there is a threshold this project chose, not a measured property of
any camera.** The sweep exists partly so that retuning them after real captures is
a visible, deliberate change rather than a quiet one.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_capture_conditions.py` | 27 |
| `tests/test_guest_identity_readiness.py` | 15 |
| `tests/test_guest_consent_deletion.py` | 8 |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  546 passed
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
```

Without the OpenCV extra or the weights: **533 passed, 13 skipped** — CI's shape.

That 546 is the whole backend suite, not B's. B owns 333; **50 are new here**.

## What this does NOT establish

**None of Stage 4's trials have been run.** This branch decides how they will be
judged and tests the consent path and the capture envelope offline. It measures
nothing about real faces.

Concretely, the readiness gate currently returns `ROLE_BASED` — meaning **on
today's evidence B does not support putting a name on screen from a face at all**.
That is not a placeholder; it is the honest answer, and it stays the answer until:

1. **Mac runtime gate with D** — the adapters have run on Windows only.
2. **Real trials** — 30 positives and 30 unknown/ambiguous, on a held-out set,
   with seats, angles and lighting varied. `cue-guests trials` and
   `cue-guests evaluate` produce and judge them ([b-stage-3.md](b-stage-3.md)).
3. **A measured calibration** — `cue-guests calibrate` on two-sided held-out pairs.
4. **B's media checks** — `docs/results/b-media-check.template.md`.

Per Stage 2's finding, drawn faces cannot substitute for real ones: SFace collapses
them into a narrow region of its embedding space, so a synthetic suite can never
move this gate.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md).
