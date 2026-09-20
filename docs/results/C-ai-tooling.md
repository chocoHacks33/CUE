# C-lane · AI-assisted development, one honest example

_Tool: Claude Code (Sonnet + Opus, running as this repo's local
assistant). Not GitHub Copilot, not the ChatGPT web UI._

## The case

The Stage-4 failure-injection tests added a scenario:
`test_duplicate_final_transcript_yields_one_decision`. It fed the
assembler the SAME `is_final=True, speech_final=True` Results frame
twice and asserted only one FinalUtterance is emitted.

The initial run failed:

```
FAILED apps/api/tests/test_failure_injection.py::
  test_duplicate_final_transcript_yields_one_decision
AssertionError: duplicate final produced 2 decisions; expected 1
```

## What I asked Claude Code

"The failure-injection test says duplicate finals should coalesce to
one decision. Right now the assembler flushes on `speech_final`,
resets its buffer, and a second identical `Results` frame is treated
as a brand-new utterance. Add a *narrow* post-flush duplicate guard:
if the SAME `(start, duration, transcript)` segment arrives before
anything new, drop it. Preserve everything else."

## What it did

Modified `apps/api/src/cue_api/speech/assembler.py`:

1. Added `self._last_flushed_signature: frozenset[tuple[Any, Any, str]]`
   to `Assembler.__init__`. Cleared on `reset(new_epoch)`.
2. In `_flush()`, captured the segment signature into
   `self._last_flushed_signature` before wiping the buffer.
3. In `feed()`, added a pre-`_accumulate` check: if the incoming
   `is_final` frame's `(start, duration, transcript)` equals the last
   flushed signature AND the buffer is empty, drop it entirely.

Also updated a pre-existing test
(`test_c_lane.py::test_on_reconnect_clears_queue_and_bumps_mode`)
that had reused the SAME `(start, duration)` for two supposedly-
different utterances — the new guard rightly rejected the second as
a literal replay. The test was updated to give the second utterance
`start: 2.0` instead of `start: 0.0`, which is what real Deepgram data
looks like.

## What I verified

- Ran `python -m pytest -q apps/api/tests/`: **539 passed, 2 skipped**.
  The specific failing test passes; no other tests regressed.
- Ran `python -m ruff check .`: clean.
- Manually reviewed the diff in `assembler.py` to confirm the guard
  scope is exactly (a) matches only immediately after flush, (b) is
  cleared on `reset(new_epoch)`, and (c) does NOT affect two separate
  utterances that happen to share text at different stream times.
- Re-read the assembler doc-comment to make sure the invariant
  (post-flush duplicate frame -> dropped, cleared on epoch reset)
  is documented in prose next to the code.
- Confirmed the git commit message calls out the pre-existing test
  update and explains WHY it needed changing so a future reader
  doesn't think the test was silenced.

## Why I trust this change

The bug the guard prevents is real (Deepgram can re-broadcast an
`is_final` frame during a network flake, per its docs). The guard is
narrow: it only compares against the *last* flushed signature, so it
cannot mask two genuinely-distinct utterances that happen to reuse a
transcript. And it's covered by a first-class test that would fail
loudly if the guard were removed or over-widened.

## Where AI helped, and where I still had to think

Claude Code was fast at:
- Locating the exact code path (assembler `_flush` + `feed`).
- Proposing a minimal data structure (`frozenset` signature) instead
  of a broader "remember all recent segments" approach.
- Spotting the reconnect test that would break under the new guard.

I had to think about:
- Whether the guard should also fire on `UtteranceEnd` re-delivery
  (decision: no — `UtteranceEnd` has no transcript to compare).
- Whether to widen the signature to include audio_epoch (decision:
  the `feed()` epoch check upstream already drops stale-epoch
  frames, so including it in the signature is redundant).
- How to explain the pre-existing-test edit in the commit so a
  reviewer sees it's not a silenced regression.

## Where AI-assisted work could have gone wrong

- **Over-widening**: an earlier draft kept `seen_seg_keys` persistent
  across `_reset_buffer()`. That would have mis-flagged real
  distinct utterances as duplicates. I caught it in review.
- **Silent test edits**: Claude's first attempt at the reconnect test
  update did not carry a comment. I added `# Give this utterance a
  distinct (start, duration) - otherwise the assembler's post-flush
  duplicate guard rightly treats it as a literal replay of the
  first.` so the change is legible in the diff.
