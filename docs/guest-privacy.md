# Guest identity: consent, storage and deletion

Owner: Person B. This describes what the code in `apps/api/src/cue_api/guests/`
and `apps/api/src/cue_api/vision/` actually does today, not an intention.

## What we ask for, and when

Nobody is identified without opt-in, event-scoped consent recorded before
enrolment. `POST /api/v1/guests` refuses an enrolment where `consentGranted` is
false, and refuses one that omits the `LIVE_IDENTIFICATION` purpose, so a guest
who agreed only to be recorded cannot be matched by face.

The spoken consent script, printed by `cue-vision enrol` before it will do
anything:

> Consent recorded for: live identification during this event, local recording
> and cloud media relay. References are held in memory on the director Mac only
> and are deleted at event end or on request.

The three purposes are recorded separately, because the guest is agreeing to
three different things: being matched by face, being recorded, and having their
video relayed through LiveKit Cloud.

## What is stored, and where

| Data | Where | Lifetime |
|---|---|---|
| Reference photo | The enrolling laptop, never uploaded | Deleted by B after enrolment |
| Reference embedding (128 floats) | Memory of the API process on D's Mac | Until withdrawal, event purge, or restart |
| Display name and aliases | Same process memory | Same |
| Latest observation per camera | Same process memory, one per camera | Overwritten by the next one; dropped on expiry, epoch change or withdrawal |
| Status tallies | Same process memory | Counts only, no per-face history |

There is no database and no disk persistence. A backend restart clears every
embedding and requires re-enrolment. That is the privacy default, not an
unfinished feature.

Reference embeddings leave the process through exactly one route: the
worker-facing `GET /api/v1/vision/gallery`, which requires the operator
credential. The guest-facing shapes (`GuestRecord`, `GuestListResponse`) carry no
embeddings at all, and both the TypeScript and Python parsers reject a guest
record that tries to carry one.

## What never happens

- A name is never inferred from a seat, a camera role, a join order or a track.
  A display name without a guest ID is rejected as a seat label.
- Face references and embeddings never enter a language-model request or an
  operational log. `Observation.as_log_record()` strips the display name.
- An unknown face stays unknown. Two faces that score too closely produce an
  abstention, not the better guess.
- A raw similarity is never reported as a confidence.

## Deletion

| Action | Endpoint | Effect |
|---|---|---|
| One guest withdraws | `DELETE /api/v1/guests/{guestId}?eventId=` | Embeddings zeroed and unlinked, reference version reset, consent marked withdrawn, live observations naming them dropped, removed from the worker gallery |
| Event ends | `DELETE /api/v1/guests?eventId=` | Every guest record and embedding for the event removed |

Both return a receipt counting what was deleted, so deletion is observable rather
than promised. After withdrawal, adding a new reference to that guest is refused;
re-enrolment means a fresh consent conversation.

The worker also drops the identity locally the moment a guest disappears from a
refreshed gallery, so a withdrawal takes effect without waiting for the next
enrolment cycle.

**Stated limitation:** Python cannot guarantee that a float list's bytes leave
process memory. `purge_references()` overwrites each vector with zeros and
unlinks it, which is best effort. The real guarantee is that nothing is written
to disk and the process is stopped at the end of the event.

## Identity is perishable

An identity is bound to one camera, one stream epoch and one local track, and it
expires 1.5 seconds after the last observation that supported it. It is dropped
when:

- the camera republishes, changes webcam or reconnects ambiguously (epoch bump);
- the camera is reframed or the track is lost;
- a frame fails the quality gate, or the face matches nobody;
- the guest withdraws consent.

A late observation does not become fresh by arriving late. Evidence from a
superseded epoch is refused with 409 rather than stored.
