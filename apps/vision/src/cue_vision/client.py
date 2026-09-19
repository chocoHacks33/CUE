"""Thin stdlib client for the guest/observation routes on D's Mac.

Stdlib only, so the worker gains no extra dependency for the sake of four HTTP
calls. Reference images never travel: only the embedding computed locally does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any

from cue_vision.gallery import ReferenceGallery

OPERATOR_HEADER = "X-CUE-Bootstrap-Secret"


class BackendError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Backend returned {status}: {detail}")
        self.status = status
        self.detail = detail


class VisionBackendClient:
    def __init__(self, base_url: str, operator_secret: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = operator_secret
        self._timeout = timeout

    def fetch_gallery(self, event_id: str) -> ReferenceGallery:
        payload = self._request("GET", "/api/v1/vision/gallery", query={"eventId": event_id})
        return ReferenceGallery.from_payload(payload)

    def post_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/vision/observations", body=observation)

    def invalidate(
        self,
        *,
        event_id: str,
        camera_id: str,
        current_stream_epoch: int,
        reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/vision/invalidate",
            body={
                "eventId": event_id,
                "cameraId": camera_id,
                "currentStreamEpoch": current_stream_epoch,
                "reason": reason,
            },
        )

    def enrol_guest(
        self,
        *,
        event_id: str,
        display_name: str,
        consent_purposes: Sequence[str],
        recorded_by: str,
        aliases: Sequence[str] = (),
        guest_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/guests",
            body={
                "eventId": event_id,
                "displayName": display_name,
                "aliases": list(aliases),
                "guestId": guest_id,
                "consentGranted": True,
                "consentPurposes": list(consent_purposes),
                "recordedBy": recorded_by,
            },
        )

    def add_reference(
        self,
        *,
        event_id: str,
        guest_id: str,
        embedding: Sequence[float],
        quality: float,
        embedder: str,
        embedder_version: str,
        captured_at_ms: int,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/guests/{urllib.parse.quote(guest_id)}/references",
            body={
                "eventId": event_id,
                "embedding": [float(value) for value in embedding],
                "quality": quality,
                "embedder": embedder,
                "embedderVersion": embedder_version,
                "capturedAtMs": captured_at_ms,
            },
        )

    def list_guests(self, event_id: str) -> dict[str, Any]:
        return self._request("GET", "/api/v1/guests", query={"eventId": event_id})

    def withdraw(self, *, event_id: str, guest_id: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/v1/guests/{urllib.parse.quote(guest_id)}",
            query={"eventId": event_id},
        )

    def purge_event(self, event_id: str) -> dict[str, Any]:
        return self._request("DELETE", "/api/v1/guests", query={"eventId": event_id})

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header(OPERATOR_HEADER, self._secret)
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except json.JSONDecodeError:
                pass
            raise BackendError(error.code, str(detail)) from error
        except urllib.error.URLError as error:
            raise BackendError(0, f"Cannot reach {self._base_url}: {error.reason}") from error

        if not raw:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
