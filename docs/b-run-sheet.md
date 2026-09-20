# B run sheet — guest identity

One page. Written to be used at 11pm by someone tired, not read in advance.

---

## 1. Before anything, check what identity is allowed to do

```bash
curl -s "$API/api/v1/guests/readiness?eventId=$EVENT" \
  -H "X-CUE-Bootstrap-Secret: $SECRET"
```

Read `namingPolicy` and say the `disclosure` field. Do not improvise around it.

| `namingPolicy` | What it means on the night |
|---|---|
| `ROLE_BASED` | **Expected today.** No name from a face. Cameras by role only. |
| `NAMED_ASSIST` | Identity suggests; **you confirm every named shot** before it airs. |
| `NAMED_AUTO` | Identity may name unattended. Only if all four evidence items passed. |

`blockingReasons` tells you why it is not more permissive. If it is not empty, the
answer to "why isn't it naming people?" is in there verbatim.

---

## 2. The sentence to say about identity

Say the `disclosure` field from that response. Today it reads:

> Cameras are chosen by role, not by face recognition. Nothing on screen is
> identified by face.

If someone asks whether the face recognition works: **"We built it and we have not
measured it, so it is switched off. You can check that on the readiness endpoint."**

That is the whole answer. It is a better answer than a number nobody verified.

---

## 3. Do not say

- That anyone was recognised.
- Any accuracy, precision or confidence figure.
- That the thresholds are tuned.
- That the vision path has run on the Mac.
- That a passing test suite means recognition works.

Full list in [b-limitations-and-licences.md](b-limitations-and-licences.md).

---

## 4. If a guest consents and you want to enrol them

Only with spoken consent, recorded, before anything else. The CLI prints the
consent script and refuses to continue without `--consent-confirmed`.

```bash
cue-guests enrol --api "$API" --secret "$SECRET" --event "$EVENT" \
  --name "Sarah" --consent-confirmed --model-dir models sarah-1.jpg sarah-2.jpg
```

The photo never leaves the laptop — only the embedding is sent. **Delete the photo
afterwards.**

Check who is enrolled:

```bash
cue-guests gallery --api "$API" --secret "$SECRET" --event "$EVENT"
```

---

## 5. If a guest changes their mind — do this immediately

```bash
cue-guests forget --api "$API" --secret "$SECRET" --event "$EVENT" --guest-id "$GUEST"
```

It returns a receipt counting what was deleted. Their references are destroyed,
their live evidence is dropped, they leave the worker gallery, and a late
observation already in flight is refused. **Show them the receipt if they want it.**

Re-enrolling later needs a fresh consent conversation; adding a reference back is
refused.

---

## 6. At the end of the event

Two steps, in this order. The first is A's and is authoritative; the second is the
proof.

```bash
# 1. A ends the event: purges guest data, revokes sessions, sets mode ENDED
curl -s -X POST "$API/api/v1/events/$EVENT/end" -H "X-CUE-Producer-Secret: $PRODUCER"

# 2. B verifies it actually happened, and files the evidence
cue-guests verify-cleanup --api "$API" --secret "$SECRET" --event "$EVENT" \
  --out docs/results/b-cleanup-record.json
```

**Step 2 exits non-zero if anything survived**, and lists what. If it does, say so
rather than moving on — that is the one failure that must not be quiet.

Expected output:

```
verdict:      clean — re-read found nothing remaining
```

---

## 7. If something is wrong

| Symptom | Likely cause |
|---|---|
| `cue-guests` says a model is missing | weights not downloaded; see [b-stage-0.md](b-stage-0.md) |
| ONNX fails to parse the model | you have a 131-byte git-lfs pointer, not the model |
| Every face matches everybody | an unnormalised embedding reached the matcher |
| `readiness` says `ROLE_BASED` and you expected more | read `blockingReasons`; it is evidence that is missing, not a bug |
| A capture is refused | `underexposed` / `overexposed` / blur / too far / clipped at the edge — the reason is named |

Nothing here is a reason to loosen a threshold during a show.
