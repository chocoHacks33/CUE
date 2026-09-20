# B — Stage 6 prep

Plan §7, Stage 6: *"overnight until Sunday 08:00: permitted accommodation and
rest. […] Use a short agreed handoff for documentation/offline regression checks if
needed, then rest. **No new media architecture, model migration or major feature.**
Hardware-dependent fixes remain unverified until tested on the actual setup."*

Branch: `codex/b-stage-6-prep`, on top of Stage 5.

**This branch is deliberately small, and that is the deliverable.** Stage 6 forbids
new features. The temptation at 01:00 is to "just finish" the identity work, and
that is precisely the change that cannot be verified before the venue reopens. So
B adds one offline check and one page of handoff, and nothing else.

## The one command

```bash
python scripts/b_offline_regression.py
```

No camera, no Mac, no model file, no network. Around twenty seconds. Exit 0 means
B's lane is where it was left:

```
  PASS  B's tests      391 passed, 285 deselected      (numbers as of this commit)
  PASS  ruff           All checks passed!
  PASS  naming policy  ROLE_BASED True False
  PASS  doc links      16 documents, every link resolves

Nothing drifted. B's lane is where it was left.
```

It checks the four things that can quietly go wrong without hardware: B's tests,
lint, **the load-bearing claim that naming is switched off**, and that every link in
B's documents resolves — a broken link in the submission is a bad look at 10:00.

Counts are not quoted in this page on purpose. They move whenever a test or a
document is added, and a handoff note that goes stale on its own is worse than one
that says less. The command prints the current numbers.

### It was verified to detect drift, not just to pass

Breaking the fail-closed default on purpose (`ROLE_BASED` → `NAMED_ASSIST`):

```
  FAIL  B's tests      E  assert <NamingPolicy.NAMED_ASSIST> is <NamingPolicy.ROLE_BASED>
  FAIL  naming policy  NAMED_ASSIST False False

DRIFTED — B's tests, naming policy. Do not change code to make this pass;
find out what moved, and whether B's documents are now untrue.
```

Exit 1. Then restored, and confirmed byte-identical.

Writing that check found a bug in the check itself: pytest's Windows output carries
cp1252 bytes (`0x97` is an em-dash), which crashed the subprocess reader thread and
degraded the detail to a bare `exit 1` plus a traceback — losing the diagnostic at
exactly the moment it matters. Decoding is now lossy rather than fatal.

## State B is in, going into the night

| | |
|---|---|
| Naming policy | `ROLE_BASED` — no name on screen comes from a face |
| Disclosure | served live at `GET /api/v1/guests/readiness`, and shown in D's compositor |
| Calibration | none; `PROVISIONAL_DEFAULT` anchor only |
| Model weights | downloaded and pinned; digests corroborated by upstream's git-lfs `oid` |
| Identity report | filed as **NOT RUN**, 0 trials in both arms |
| Media checks | filed as **NOT RUN** |
| Submission statement | [b-limitations-and-licences.md](b-limitations-and-licences.md), pinned to the code by tests |

## Safe to do overnight

- Run the regression check above.
- Read and correct **documentation** — but if you change a number, the freeze tests
  will tell you the submission document now disagrees with the code. That is the
  point; fix whichever is wrong.
- Re-read [b-run-sheet.md](b-run-sheet.md) so it is familiar before it is needed.

## Not safe, and not permitted by the plan

- **Retuning any threshold.** `accept_similarity`, `margin`, confirmations, window,
  TTL. They are unmeasured, and changing an unmeasured number overnight replaces one
  guess with another while invalidating the submission document.
- **Loosening the readiness gate** to make identity name people. There is no
  evidence for it, and the gate reporting `ROLE_BASED` is the honest answer rather
  than a bug to route around.
- **Model migration.** Explicitly forbidden, and the current weights are pinned and
  verified.
- **Any camera or Mac work.** The venue is closed and a hardware-dependent fix
  stays unverified until tested on the actual setup.

## At 08:00 — B's Stage 7 sequence

Stage 7 asks B to *"reframe guest camera, re-enrol after memory-clearing restart,
check unknown rejection in current lighting."* All three need hardware. The commands
are here so they take minutes rather than an hour.

```bash
export API=http://…  SECRET=…  EVENT=…  PRODUCER=…
```

**1. Confirm what identity is allowed to do, before anything else.**

```bash
curl -s "$API/api/v1/guests/readiness?eventId=$EVENT" -H "X-CUE-Bootstrap-Secret: $SECRET"
```

**2. Re-enrol after the restart.** The backend is memory-only by design, so a
restart clears every embedding — that is the privacy default, not a fault. Every
guest must consent again, out loud, before re-enrolment.

```bash
cue-guests enrol --api "$API" --secret "$SECRET" --event "$EVENT" \
  --name "Sarah" --consent-confirmed --model-dir models sarah-1.jpg
cue-guests gallery --api "$API" --secret "$SECRET" --event "$EVENT"
```

**3. Reframe the guest camera**, then void the identity it supported. A reframe
invalidates identity even when the stream epoch has not moved:

```bash
curl -s -X POST "$API/api/v1/guests/invalidate" \
  -H "X-CUE-Bootstrap-Secret: $SECRET" -H "Content-Type: application/json" \
  -d '{"eventId":"'"$EVENT"'","cameraId":"CAM-GUEST","currentStreamEpoch":1,
       "reason":"reframed after overnight move"}'
```

Moving a laptop changes framing, so this is not optional after an overnight pack.

**4. Check unknown rejection in this morning's lighting.** Point the guest camera
at somebody who is **not** enrolled and confirm the observation comes back
`UNKNOWN` or `AMBIGUOUS`, never a name:

```bash
curl -s "$API/api/v1/guests/observations?eventId=$EVENT" -H "X-CUE-Bootstrap-Secret: $SECRET"
```

If an unenrolled person is named even once, that is the worst outcome this project
can produce. Stop, leave the gate on `ROLE_BASED`, and say so.

**5. If the trials actually get run**, the sequence is in
[b-stage-3.md](b-stage-3.md), and `cue-guests evaluate` exits non-zero while the run
cannot support a claim. Filling in the identity report will fail
`test_the_identity_report_on_disk_still_records_no_trials` **on purpose** — that
tripwire exists so the report, the readiness claim and the disclosure get revisited
together rather than one at a time.

## Verified

```
python scripts/b_offline_regression.py  ->  4/4 PASS, exit 0
deliberate drift                        ->  2 FAIL, exit 1, names what moved
cd apps/api && python -m pytest -q      ->  670 passed, 6 skipped
cd apps/api && python -m ruff check .   ->  All checks passed
```

## What this does NOT establish

Nothing new about identity, on purpose. **This branch adds no capability.** Stage 6
is rest, the venue is closed, and B's four outstanding items — Mac gate, real
trials, measured calibration, media checks — are all hardware and all still open.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md),
[b-stage-5-prep.md](b-stage-5-prep.md), [b-stage-5.md](b-stage-5.md).
