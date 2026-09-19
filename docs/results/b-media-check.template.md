# B media check — CAM-GUEST

Copy to `b-media-check.md` and fill in as each test is actually run. Leave
entries as NOT RUN until then. No secrets, no raw recordings in Git.

- Date/time:
- Commit SHA:
- B laptop: OS / CPU architecture / RAM / free storage:
- Browser and version:
- Selected webcam (device label):
- Camera ID / stream epoch observed on D:

## Test 1 — local capture on B's Windows laptop (due H2)

Video only. Do **not** enable B's microphone to make a test pass; CAM-GUEST is
video-only by contract and a captured audio track is a failure, not a bonus.

- 30-60 s local clip recorded with a distinctive visual marker: NOT RUN
- Audio tracks in the saved file (must be zero): NOT RUN
- File played back outside the app: NOT RUN
- Container/MIME actually produced:
- Duration:
- Private artifact location (not committed):

## Test 2 — CAM-GUEST received on D's Mac (due H3)

- B's physical marker visible in D's preview: NOT RUN
- Server-issued label reads `CAM-GUEST`: NOT RUN
- Decoded frames arriving, not just a connected socket: NOT RUN
- D recorded and played back a clip of B's feed: NOT RUN

## Test 3 — B receives another laptop remotely (due H6)

- Observer session opened with an identity distinct from B's publisher: NOT RUN
- Which source was recorded (A or C):
- A's master audio present in the recording: NOT RUN
- Clip played back locally: NOT RUN
- Observer tab closed afterwards: NOT RUN

## Test 4 — vision runs on D's Mac (B's own runtime gate)

- OpenCV wheel installs on D's Python/architecture: NOT RUN
- Both model files downloaded and checksums pinned: NOT RUN
- Licences read and verified against the downloads: NOT RUN
- One real face detected on a live CAM-GUEST frame on the Mac: NOT RUN
- One enrolment completed end to end with a consenting person: NOT RUN

## Issues, limitations and anything disabled

- Verified by B:
- Witnessed by:
