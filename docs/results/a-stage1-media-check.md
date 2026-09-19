# Person A Stage 1 media check

- Branch: `codex/person-a-stage-1`
- Exact commit: fill after push
- Windows device/browser: NOT RUN
- D Mac configuration: NOT RUN
- Private local clip location: NOT RUN
- Private remote clip location: NOT RUN

| Check | Result | Evidence |
|---|---|---|
| Automated pairing/admission tests | PASS | API test suite |
| Frame/PCM contract tests | PASS | API test suite |
| TypeScript contract/client tests | PASS | contracts and web test suites |
| A local `CAM-HOST` clip records and plays | NOT RUN | Requires A's webcam |
| Pairing colour/code physically matches D | NOT RUN | Requires D's Mac |
| D receives fresh decoded A frames | NOT RUN | Requires real LiveKit session |
| D receives only A's master audio | NOT RUN | Requires real LiveKit session |
| Remote A clip records and plays on D | NOT RUN | Requires D's Mac |
| Replayed pairing token is rejected | PASS (automated) | Physical repeat recommended |

Stage 1's team exit gate remains closed until the physical NOT RUN rows pass.
