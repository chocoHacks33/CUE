# D Stage 7: Sunday morning re-establish and validate

Status: **NOT RUN — Sunday morning, on the Mac, with the three Windows laptops publishing.**

Plan Stage 7 (D): recheck all mappings, A's audio, clap and flash timing, 20-minute final soak and recording playback, rehearse the pitch. Exit gate: claims match today's conditions; a capability that fails is disabled and disclosed, and the saved submission updated.

Commit running: `________________`  Tag: `________________`  Operator/time: `________________`

## 1. Automated preflight

```bash
apps/api/.venv/bin/python scripts/d_morning_preflight.py --api http://127.0.0.1:8000 --event hackmit-demo
```

Paste the output. Every automated line must read GO before any physical row is attempted.

```
(paste here)
```

## 2. Physical rows

| Row | Result | Evidence |
|---|---|---|
| CAM-HOST tile shows A's laptop number | NOT RUN | |
| CAM-GUEST tile shows B's laptop number | NOT RUN | |
| CAM-WIDE tile shows C's laptop number, usable safety view | NOT RUN | |
| A's audio audible on headphones from host and guest positions; one master track in the log | NOT RUN | |
| Clap and flash, host angle (`scripts/av_skew.py`) | NOT RUN | p95 abs skew ms: |
| Clap and flash, guest angle | NOT RUN | p95 abs skew ms: |
| Clap and flash after 15 minutes | NOT RUN | p95 abs skew ms: |
| Final soak (20 min, or state the shorter length) | NOT RUN | export file: |
| Manual cuts during the soak (Stage 4 gate) | NOT RUN | p95 ms over N cuts: |
| Failovers during the soak (Stage 4 gate) | NOT RUN | max ms over N trials: |
| Recording verified (`scripts/verify_recording.py`) and played in VLC or Chrome | NOT RUN | sha256: |
| Pitch rehearsal with the live segment (`docs/DEMO-D.md`), timed | NOT RUN | duration: |

## 3. Exit gate: claims match today's conditions

| Claim the pitch makes | Measured today? | Where |
|---|---|---|
| Future mention holds | NOT RUN | beat 1 rehearsal |
| Immediate introduction produces a suggestion the desk takes | NOT RUN | beat 2 rehearsal |
| Covered camera fails over to wide within the measured time | NOT RUN | Failovers row |
| HOLD beats a late AI decision | NOT RUN | beat 4 rehearsal, timeline entry |
| Names on screen: none (ROLE_BASED) or B's morning validation filed today | NOT RUN | preflight line "naming policy and disclosure" |

Capabilities disabled or disclosed today: `________________`

Submission updated to match (A saves; D confirms the wording about D's rows): NOT RUN
