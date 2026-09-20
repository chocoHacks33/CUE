# B media check — CAM-GUEST

**Status: NOT RUN.** No camera has published to this system from B's laptop, and
nothing has been received on D's Mac. Recorded here so the gap is explicit at scope
freeze.

- Date/time: not run
- Commit SHA: not run
- B laptop: Windows 11 Home 10.0.26200, x86-64, Python 3.14.7 — used for
  automated tests only, never for a capture
- Browser and version: **not run** — Node is not installed on this machine, so the
  web publisher has never been started here. The TypeScript suites rest on CI.
- Selected webcam (device label): none selected
- Camera ID / stream epoch observed on D: none

## Test 1 — local capture on B's Windows laptop (due H2)

- 30-60 s local clip recorded with a distinctive visual marker: **NOT RUN**
- Audio tracks in the saved file (must be zero): **NOT RUN**
- File played back outside the app: **NOT RUN**
- Container/MIME actually produced: unknown
- Duration: —
- Private artifact location: none

What *is* verified, by automated test rather than by capture: `CAM-GUEST` is
declared `audioPolicy: "DISABLED"` in the shared camera contract, and
`validateCapturedTracks` throws if a non-host camera presents an audio track. So
the contract forbids guest audio. Nobody has yet confirmed the browser honours it
with a real webcam.

## Test 2 — CAM-GUEST received on D's Mac (due H3)

- B's physical marker visible in D's preview: **NOT RUN**
- Server-issued label reads `CAM-GUEST`: **NOT RUN**
- Decoded frames arriving, not just a connected socket: **NOT RUN**
- D recorded and played back a clip of B's feed: **NOT RUN**

## Test 3 — B receives another laptop remotely (due H6)

- Observer session opened with an identity distinct from B's publisher: **NOT RUN**
- Which source was recorded: —
- A's master audio present in the recording: **NOT RUN**
- Clip played back locally: **NOT RUN**
- Observer tab closed afterwards: **NOT RUN**

## Test 4 — vision runs on D's Mac (B's own runtime gate)

This is the one test with partial results, and the partial results are all from
**Windows, not the Mac**. The distinction is the whole point of the test, so each
row says which machine it was done on.

| Check | Status |
|---|---|
| OpenCV wheel installs on D's Python/architecture | **NOT RUN** — installed on Windows (`opencv-python` 4.14.0, numpy 2.5.3); D's macOS/arch is untested |
| Both model files downloaded and checksums pinned | **DONE (Windows)** — digests pinned in `guests/face_models.py`; YuNet's matches upstream's git-lfs `oid` |
| Licences read and verified against the downloads | **DONE** — upstream `LICENSE` files fetched and read: MIT (© 2020 Shiqi Yu), Apache-2.0 |
| One real face detected on a live CAM-GUEST frame on the Mac | **NOT RUN** — YuNet has detected a *drawn* face on Windows (score 0.76, 5 landmarks). No live frame, no real face, no Mac |
| One enrolment completed end to end with a consenting person | **NOT RUN** — `cue-guests enrol` has completed end to end against a local API using a drawn image, with no person involved and no consent recorded |

## Issues, limitations and anything disabled

- **Nothing is disabled.** The gaps above are unstarted work, not switched-off
  features.
- One real defect was found by running the models on Windows and is fixed: SFace
  returns an unnormalised embedding (measured norm ≈ 3.9). Since
  `cosine_similarity` is a plain dot product of unit vectors, an unnormalised probe
  would have inflated every similarity several-fold and named everybody. It was
  never live — both call sites normalised — but it is now normalised at the source.
- Because Test 4 has not run on the Mac, B's identity work is **untested against
  real pixels on the machine that will run the show**. The readiness gate reflects
  this: it returns `ROLE_BASED`, so no name on screen comes from a face.
- Verified by B: the Windows-only rows above, all by automated test or local
  command, each stated with the machine it ran on.
- Witnessed by: nobody. None of the hardware checks have been performed.
