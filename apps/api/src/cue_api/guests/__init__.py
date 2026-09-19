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
  types.py, version.py  internal value types and version strings
  adapters/             OpenCV YuNet + SFace, imported lazily

Only `adapters/` needs a native wheel, so everything else imports and tests
on every machine in the team. Live observations are Stage 2 and are not here.
"""

from cue_api.guests.registry import GuestRegistry
from cue_api.guests.router import build_guest_router

__all__ = ["GuestRegistry", "build_guest_router"]
