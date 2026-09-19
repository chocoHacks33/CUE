# Person A Stage 2 integration check

Commit tested: `NOT RUN`

Mac model / macOS / browser: `NOT RUN`

Event ID: `NOT RUN`

| Gate | Result | Evidence / measurement |
|---|---|---|
| Automated API, contract and web tests | NOT RUN ON MAC | |
| Fixture cue → real policy → real canvas cut → ACK | NOT RUN | |
| All three decoded slots report advancing frames | NOT RUN | |
| Observer cannot ACK, reconcile or report readiness | NOT RUN | |
| Manual TAKE works on HOST, GUEST and WIDE | NOT RUN | |
| HOLD invalidates a pending AUTO command | NOT RUN | |
| Camera/epoch mismatch is rejected | NOT RUN | |
| Backend restart rejects old ACK and reconciles actual output | NOT RUN | |
| Covered/stopped source reaches safe wide or slate | NOT RUN | |
| `CAM-HOST` remains the only audio source through cuts | NOT RUN | |
| 30-cut TAKE-to-ACK p95 is below 300 ms | NOT RUN | |
| Real three-camera recording plays independently | NOT RUN | |
| Clap/flash A/V timing checked | NOT RUN | |
| Worker-active Mac load is acceptable | NOT RUN | |

Do not change a row to PASS from a synthetic fixture, connection icon or local
Windows test. Attach a real recording, screenshot, log excerpt or measurement.
