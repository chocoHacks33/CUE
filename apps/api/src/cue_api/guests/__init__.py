"""Person B — guest identity: consent, enrolment references and face capture.

Stage 0/1 scope, one package:
  contracts.py          the wire vocabulary, mirrored in packages/contracts
  registry.py           consent roster, references, deletion receipts
  router.py             the guest and gallery routes
  face_models.py        model files, licences and checksums
  capture_quality.py    the capture-quality gate
  reference_gallery.py  enrolled references as plain float tuples
  enrolment_cli.py      the cue-guests command
  backend_client.py     stdlib HTTP client for that command
  observation_store.py  latest observation per camera, epoch-aware
  observation_pipeline.py  frame in, observations out
  face_matching.py      gallery matching with a real abstention
  face_tracking.py      IoU track association inside one camera epoch
  identity_ledger.py    confirmation, expiry, epoch and consent invalidation
  confidence_calibration.py  similarity -> confidence, provisional anchor only
  types.py, version.py  internal value types and version strings
  adapters/             OpenCV YuNet + SFace, imported lazily

Only `adapters/` needs a native wheel, so everything else imports and tests
on every machine in the team.
"""

from cue_api.guests.observation_store import ObservationStore
from cue_api.guests.registry import GuestRegistry
from cue_api.guests.router import build_guest_router

__all__ = ["GuestRegistry", "ObservationStore", "build_guest_router"]
