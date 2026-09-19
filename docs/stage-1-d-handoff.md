# Person D Stage 1 handoff

Branch `codex/person-d-stage-1`, built on `codex/stage-0-integration` (18eeb22). Mac: macOS 26.3, Apple silicon, Python 3.14.5, Node 25.9.0, Chrome 153. Date: 2026-09-19 (Boston).

Stage 1 for D in the v3 plan is: own the remotely received A recording, show all three source previews, and make the recorder available to teammates. The previews shipped in Stage 0. This branch adds the recorder route, the readiness contract A asked D for, and the Mac runtime gate B asked D for. The remote A recording still needs A to publish.

## 1. Recorder available to every laptop: `/recorder`

`apps/web/src/recording/RecorderPage.tsx`, routed at `/recorder` (or `#/recorder`). Any laptop opens it, picks its camera ID, captures its own webcam under A's `captureConstraints` and `validateCapturedTracks` (imported, not copied), records with the shared `RecordingTest` component, downloads the clip with the real container extension, and plays it outside the app. It never joins a room. This is Test 1 in v3 section 6 without touching A's publisher page; A can still embed `RecordingTest` in the publisher later using the already-acquired stream.

Run: `npm run dev:web`, open `http://localhost:5173/recorder`. Close the publisher tab first so the webcam is not held by two pages.

## 2. Readiness contract (D produces, A and C consume)

`packages/contracts/src/readiness.ts`, exported from the contracts index. `apps/web/src/producer/readiness.ts` builds it from the receiver's slot state every 250 ms; the producer page shows the live payload in a "Readiness contract preview" panel so A can see real values before wiring the control socket.

| Field | Meaning |
|---|---|
| `rendererId`, `rendererGeneration` | Stable per tab; generation increments on every (re)connect. A second tab is a different renderer and cannot ACK for this one |
| `clockDomain: "renderer-monotonic"`, `reportedAtMs` | Browser `performance.now()`. The backend must map clock domains explicitly, never compare raw |
| `currentSource` | Null until the Stage 2 compositor draws a source |
| `masterAudio` | CAM-HOST track SID, attached, browser playback allowed |
| `slots[3]` in `CAMERA_IDS` order | per camera: publisher identity, stream epoch, track SIDs, `decoded`, `renderable` (decoded and not stalled), `lastFrameAgeMs`, `framesProgressing` since the previous snapshot, frame count, dimensions, state |

`isReceiverReadiness()` is a structural validator for the backend side. Tests: `packages/contracts/src/readiness.test.ts`, `apps/web/src/producer/readiness.test.ts`. A: if you want a Python mirror in `cue_api/contracts.py` I can write it, or you can, since that file is yours.

## 3. Mac runtime gate for B (B's handoff, "what has to happen next" item 1)

Actually run on the Mac, in `apps/api/.venv`:

| Check | Result |
|---|---|
| `pip install -e "apps/vision[opencv,dev]"` with B's pin `opencv-python>=4.10,<5` | PASS: resolved `opencv-python 4.14.0.94`, `numpy 2.5.3`, wheels exist for cp314 arm64 |
| `cv2.FaceDetectorYN`, `cv2.FaceRecognizerSF`, `cv2.dnn` present | PASS |
| `cue_vision.adapters.opencv_models` imports | PASS |
| `apps/vision` pytest with OpenCV installed | PASS: 61 tests |
| Model files downloaded to git-ignored `apps/vision/models/` from opencv_zoo raw URLs | PASS: real binaries, not LFS pointers. YuNet 232,589 bytes; SFace 38,696,353 bytes |
| `YuNetDetector(model_dir=models).detect()` on a synthetic 1280x720 noise frame | PASS: 0 faces (expected), 1,586 ms cold including model load, 20 ms warm; `SFaceEmbedder` constructs |

Digests from `python -m cue_vision.cli models --model-dir models` on this Mac. B owns pinning them into `models.py` and `docs/vision-models.md` and verifying the licences; I did not edit B's files.

```
yunet  face_detection_yunet_2023mar.onnx    8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
sface  face_recognition_sface_2021dec.onnx  0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79
```

The noise-frame run proves the model loads and inference executes on this machine. It proves nothing about detecting a real face; that is B's item 3 with a consenting photo.

## 3b. Producer pairing panel (on top of A's Stage 1 admission)

Merged `codex/person-a-stage-1` (1309f27) into this branch with no conflicts. `apps/web/src/producer/PairingPanel.tsx` uses A's `pairingApi.ts` unchanged:

- Producer secret is typed into the panel, held in component state only, sent as `X-CUE-Producer-Secret`. It never goes into a token, URL or the publisher form.
- Per camera slot: mint a single-use pairing token, show the verification code, copy the token to send to the operator, show the authoritative binding (participant identity, device session, stream epoch, current video SID) once the exchange completes.
- Claims list polls every 2 s while a secret is entered. Pending claims first. Approve only after checking the code on the physical laptop matches; Reject otherwise. Status changes go to the receiver log.
- Pure helpers with tests in `pairingView.ts`.

Flow for the physical test: D mints CAM-HOST token, sends only the token to A. A claims; both screens show the same code. D approves. A previews and publishes. The CAM-HOST tile binds by metadata as before, now with the device session ID present.

## 4. Not run, needs teammates

| Item | Needs |
|---|---|
| Test 2: A's real feed recorded on the Mac, played back from disk | A publishing CAM-HOST |
| Three feeds received on the Mac with physical markers | A, B, C publishing |
| Test 3: each Windows laptop records another laptop's feed as an observer | observer sessions; the receiver token endpoint already supports `receiverRole: "OBSERVER"` |
| Stage 1 exit gate | all of the above |

## 5. Found while verifying on the Mac

| Finding | Effect | What I did | Owner to decide |
|---|---|---|---|
| `cue_api/semantics/parser.py` calls `load_dotenv()` at import time, and `tests/test_director.py` imports it | On any machine with a real `.env`, the whole pytest session sees the credentials in `os.environ`, so A's `test_health_distinguishes_liveness_from_readiness` (which builds `Settings(_env_file=None)` and expects 503) fails. It passes on machines with an empty `.env`, which is why nobody saw it before the Mac had credentials. The running API is unaffected because `main.py` never imports the parser | Made that one test hermetic with `monkeypatch.delenv` (cross-owner edit in A's test file, 6 lines) | C: consider moving `load_dotenv()` out of import time into the client factory so importing a module has no environment side effect |
| Editable installs of `cue_api` and `cue_vision` in `apps/api/.venv` stopped resolving (`ModuleNotFoundError`) although `pip show` listed them; pytest still passed via `pythonpath = ["src"]` | Any script using the venv interpreter directly, including uvicorn started from another directory, could fail to import | Re-ran `pip install -e` for both; imports resolve again | Environment only, nothing in the repo |
| Finder-style duplicate directories (`node_modules/@types/react 2`, `.vite/vitest 2`, and others) appeared inside `node_modules` between two green builds and broke `tsc` with TS2688 | `npm run typecheck` and `npm run build` failed | Deleted `node_modules`, ran `npm ci`; no source files were duplicated | Probably a sync tool on this Documents folder. If a `* 2` file ever shows up in `git status`, do not commit it |
