# Person D Stage 5 handoff: freeze and capture tooling

Branch `codex/person-d-stage-5`, on top of the Stage 4 integration (trunk 53f2c02). Date: 2026-09-19 (Boston).

Stage 5 for D in the v3 plan: independently play the official recording, make a permitted backup copy, save screenshots and the exact Mac configuration. All four are physical steps on the night. What shipped is the tooling that makes each one a command with an honest, checkable output, plus the results template with every row NOT RUN: `docs/results/d-stage5-freeze.md`.

## 1. Recording verifier (`scripts/verify_recording.py`)

The browser that wrote the file is not an independent check of it. The verifier decodes the file end to end with ffmpeg, a different decoder, and reports what is really there:

- container, video codec and resolution, audio codec, sample rate and channels;
- decoded length of the picture and of the sound separately, frame count, and every decode error line. MediaRecorder WebM often has no duration in its header, so decoded lengths are what count;
- SHA-256 and size;
- checks: video present, audio present (the master mic), 1280x720, both streams decode cleanly, picture and sound lengths agree within 0.5 s, and an optional minimum length. Verdict pass or fail; exit 0, 1, or 2 when the file cannot be read.

`--backup DIR` copies the file byte for byte, proves the copy's checksum equals the source, and writes a manifest beside it (size, checksum, codecs, decoded length, git commit, time). `--mp4 OUT` writes a derived H.264/AAC copy for players that do not open WebM; the manifest marks it derived, and it is not the official recording. `--markdown` prints the block for the results file.

Tests: `apps/api/tests/test_verify_recording.py` (7): synthetic VP8/Opus WebM clips rendered by ffmpeg, so the test proves the verifier reads codecs and lengths and notices a truncated or wrongly sized file. Skipped where ffmpeg with libvpx and libopus is absent.

## 2. Mac configuration snapshot (`scripts/mac_config_snapshot.py`)

One command that renders the Markdown block the results files have carried by hand since Stage 0: macOS version and build, chip, memory, free disk, git commit, branch, dirty flag and tags, Python and the package versions that matter, Node and npm, Chrome, ffmpeg, which expected processes are running, and for each environment file the variable **names** and which names from `.env.example` are missing. No value is ever read into the output; a test writes a fake secret to a temp `.env` and asserts it never appears. Tests: `apps/api/tests/test_mac_config_snapshot.py` (5).

Finding from running it here: the API venv has `livekit-api` (token minting) but not `livekit` (the rtc SDK the worker imports); the repo-root `.venv` has `livekit` 1.1.19. The worker must run from the venv that has it. Recorded in the runbook.

## 3. Programme stills (compositor)

`Save programme still` writes a PNG of exactly what the programme canvas shows, named `cue-still-<event>-<source>-<time>.png`, and logs whether the picture was live or not yet drawn. Test: `recorderSupport.test.ts` for the name.

## 4. Verification actually run (this Mac)

| Check | Result |
|---|---|
| `npm run typecheck`, `npm test`, `npm run build` | clean, 207 passed (53 contracts, 154 web), build OK |
| `apps/api` pytest and ruff | 641 passed, 13 skipped (12 new; skips are B's OpenCV weights); ruff clean, also on both scripts |
| `scripts/mac_config_snapshot.py` on this Mac | renders; env names only; found the livekit venv split |

Not run: every row of `docs/results/d-stage5-freeze.md`. There is no official recording yet because no live feed has reached this Mac at any stage.

## 5. For A

A's release preflight approval has `stage4Gates.D`, `macValidation.*` and `ownerSignoffs.D`. The freeze results file lists which row of D's evidence backs each field. D will not sign off on a recording the verifier has not passed and a human has not played through.

## 6. Runbook

`docs/stage-0-d-mac-run.md`: "Stage 5: freeze, capture, backup" and "Sunday morning: re-establish".
