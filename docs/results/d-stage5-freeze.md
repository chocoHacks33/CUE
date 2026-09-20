# D Stage 5: freeze and capture

Status: **NOT RUN — needs the official programme recording from a real three-feed session.**

Plan Stage 5 (D): independently play the official recording, make a permitted backup copy, save screenshots and the exact Mac configuration. Tooling is in `docs/stage-5-d-handoff.md`. Recordings, backups, stills and the private manifest never go in Git; this file records what was done and the checksums, not the files.

## 1. Deployed build

| Item | Value |
|---|---|
| Commit running on the Mac | `________________` |
| Release tag (A tags after the preflight) | `________________` |
| Tree clean at run time | NOT RUN |

## 2. Exact Mac configuration

Paste the output of:

```bash
apps/api/.venv/bin/python scripts/mac_config_snapshot.py
```

It lists environment variable names only, never values. Check that "Missing vs `.env.example`" reads `none` and that Running shows `uvicorn` (and `ngrok` if tunnelled).

```
(paste here)
```

## 3. Official programme recording

Run on the file the compositor downloaded after the official session:

```bash
apps/api/.venv/bin/python scripts/verify_recording.py <programme.webm> --min-seconds 120 --markdown
```

| Item | Result |
|---|---|
| File name, size, SHA-256 | NOT RUN |
| Container, video codec and resolution, audio codec | NOT RUN |
| Decoded picture length, frames; decoded sound length; difference | NOT RUN |
| Decode errors | NOT RUN |
| Verifier verdict | NOT RUN |
| Independent playback by a human, start to end, in VLC or Chrome (WebM does not open in QuickTime) | NOT RUN |
| Audio continuous across every cut, no restart at any switch | NOT RUN |
| A/V skew (`scripts/av_skew.py`, from the clap tests) | NOT RUN |

## 4. Permitted backup copy

```bash
apps/api/.venv/bin/python scripts/verify_recording.py <programme.webm> --backup <private backup dir> --min-seconds 120
```

| Item | Result |
|---|---|
| Backup location (private, not in Git) | |
| Copy SHA-256 equals source | NOT RUN |
| Manifest written next to the copy | NOT RUN |
| Derived MP4 for players without WebM (optional, `--mp4`), labelled derived | NOT RUN |
| Consent covers keeping this copy (plan section 6) | NOT CONFIRMED |

## 5. Screenshots

`Save programme still` on the compositor writes a PNG of the canvas named by event, on-air source and time. Take at least: slate, each camera on air, the failover picture, the mode strip in DEGRADED, and the disclosure line.

| Still | Taken | Private location |
|---|---|---|
| slate | NOT RUN | |
| CAM-HOST on air | NOT RUN | |
| CAM-GUEST on air | NOT RUN | |
| CAM-WIDE on air | NOT RUN | |
| failover to wide | NOT RUN | |
| mode strip with disclosure | NOT RUN | |

## 6. Final rehearsal and packing (plan Stage 5, everyone)

| Item | Result |
|---|---|
| Final live rehearsal on the frozen commit | NOT RUN |
| Laptops packed; framing to be revalidated Sunday morning | NOT RUN |

## 7. What D certifies to A's release approval

A's `docs/results/stage5-release-approval.json` has fields D owns. Fill them only from the rows above.

| Field | Current value | Evidence |
|---|---|---|
| `stage4Gates.D.status` | INCOMPLETE | `docs/results/d-stage4-check.md` |
| `macValidation.cleanStartup` | false | runbook clean start on the frozen commit |
| `macValidation.threeFeeds` | false | three decoded feeds on the Mac with markers |
| `macValidation.recordingPlayback` | false | sections 3 and 4 above |
| `macValidation.runbookVerified` | false | private runbook walked through once |
| `ownerSignoffs.D` | false | all of the above |
