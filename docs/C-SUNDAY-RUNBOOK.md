# C-lane · Sunday morning runbook

_Follow this list in order. Do NOT skip a step. If a step fails, stop
and read the "if it fails" line._

## 0. Repo

```bash
cd /path/to/CUE
git fetch --all --prune
git checkout person-c-stage-5   # or a newer team integration branch
git pull --ff-only
cd apps/api && python -m pip install -e ".[dev,desk]"
cd ../..
```

If it fails: `git status` — there should be nothing dirty. If a
teammate has integrated my work, checkout `codex/stage-5-integration`
(or the newest such branch that contains `person-c-stage-5`).

## 1. Preflight (with keys)

```bash
# In .env or exported before the run:
#   OPENAI_API_KEY       (required)
#   DEEPGRAM_API_KEY     (required)
#   CUE_MODEL=<pinned>   (required — never leave unset)
python scripts/demo_preflight.py
```

Every line must read `[GO]`. `VERDICT: GO - every check passed.`

If it fails: read which line is `NO-GO`. `OPENAI_API_KEY missing` /
`DEEPGRAM_API_KEY missing` / `CUE_MODEL not set` → set them and re-run.
`Mic level 0` → check the mic is not muted at the OS level.
`Roster loads` failed → do NOT proceed; the model can't do named
takes without the roster.

## 2. Mic test in real hall noise

Two-minute test with the real mic where it will sit, saying the five
demo sentences out loud at demo volume:

1. "Please welcome Sarah Tan."
2. "Priya, could you jump in?"
3. "Actually Sarah — sorry, Daniel."
4. "Please welcome Sarah and Daniel."
5. "Thanks both. Back to me."

Run the desk in mic + Flux:
```bash
apps/api/.venv/Scripts/python.exe prototypes/desk/server.py \
  --source mic --model flux-general-en
```
Open <http://127.0.0.1:8765>. Speak the five lines. Watch:
- Deepgram raw feed: every sentence lands as a green "Sentence" row.
- Understood card: each sentence resolves to a plain reason.
- Decisions log: `Cut to Sarah`, `Cut to Priya`, `Cut to Daniel`, one
  `Wide`, `Cut to host`.
- `final_ms` in the strip and the Signal card: **≥ 300 ms** on
  nova-3, ≥ ~30 ms on Flux. Sub-floor readings display `-` and log
  `WARN` on stderr — that means the timestamp math slipped, not a
  fast reading.

If it fails: check the Deepgram raw feed FIRST. If words are wrong,
the mic is the problem, not CUE. If words are right but decisions
aren't, the parser needs `CUE_MODEL` set (see step 1).

## 3. Caption accuracy

```bash
python scripts/run_semantic.py --models "$CUE_MODEL" --set dev
```

Writes `scripts/results_dev_<model>_<ts>.json`. Read the `summary`
block at the bottom of stdout. **`wrong_cuts` must be 0.**

If wrong_cuts > 0 on the dev set, do NOT run the held-out set — the
prompt needs another look and that is not a Sunday-morning fix.

## 4. Confirm the master audio is the host mic

Master audio never restarts on a video cut. Check:

- On the Mac, master audio channel = host mic. NOT the guest mic, NOT
  a scene aggregate.
- LiveKit publisher: audio track = master audio, video track = per
  camera. When a video cut fires, only the video track cuts.
- Test: in mic mode, press `1` / `2` / `3` in the desk. Listen: the
  audio stays continuous while the picture switches. If audio drops
  or restarts, stop the demo; the audio routing is wrong.

## 5. Release evaluation (Mac with the OpenAI key)

```bash
python scripts/release_eval.py
```

Fills the release-gate cells. Refuses if the SYSTEM prompt hash
changed since the last held-out run without `--acknowledge-retune`.
Writes:
- `docs/results/C-release-eval.md`
- `docs/results/C-release-eval.json`
- `docs/results/heldout_runs.jsonl` (append-only)

## 6. Live latency (Mac with both keys + mic)

```bash
python scripts/latency_run.py
```

Reads the 12 scripted sentences (prompts on stdout). Prints per-hop
p50/p95 for `final_ms`, `cue_decide_ms`, `total_ms` and writes
`docs/results/C-latency.md` + `.json`.

## 7. Decision box — AUTO vs ASSIST

Fill this with the numbers from steps 5 and 6, then check the box.

```
[ ] AUTO — all three must be true:
      heldout.wrong_cuts        == 0
      heldout.pass_rate         >= 0.90
      hops.total_ms.p95         <= 2500

[ ] ASSIST + role-based — everything else. Say once, out loud, at the
    top of the demo:
    "CUE is doing camera direction from role mappings — it isn't
     face-recognising anyone tonight. Every suggestion is confirmed
     by me before it fires."
```

## 8. Fill the pitch numbers

Grab the numbers from the results files (paths in step 5 and 6) into
the pitch deck. The mapping is in `docs/results/C-stage4.md` under
"Pitch-number checklist". Every bracketed placeholder in the pitch
maps to one JSON key in one of these files:

```
docs/results/C-release-eval.json
docs/results/C-latency.json
docs/results/C-soak.md
```

Do NOT hand-copy numbers you did not run. Any placeholder without a
source stays as `NOT RUN` and you say so out loud.

---

## Fallback ladder (if something goes down mid-demo)

1. **Semantic engine down** (OpenAI 5xx / rate-limited): flip to
   **ASSIST**. The desk shows suggestions, you tap `1/2/3` to accept.
   Say: "Semantic engine is down, I'm running in assist mode."
2. **Deepgram down**: **captions only → manual only**. Say: "ASR is
   down, I'll switch by hand." Use `1/2/3`, `H`, `A`.
3. **Everything down**: run `scripts/fixture_cues.py` alongside the
   desk (or `--source fixture` on the desk). Every line is stamped
   `source=FIXTURE` and the header shows the fixture chip. Say: "This
   is a scripted timeline, marked FIXTURE on screen."

## Do-not-touch (freeze rules)

- Never edit `scripts/data/heldout.json`. It is a measurement
  instrument.
- Never change `cue_api.semantics.parser.SYSTEM` on Sunday. If you
  even think about it, stop.
- Do not commit any file that contains a secret. Preflight step 1
  catches missing secrets; do not silence it with a hard-coded value.
