from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from cue_api.control import ControlError, ControlSessionStore, ControlStore
from cue_api.control_contracts import (
    ControlLatencyMetrics,
    ControlMutationResponse,
    ControlRole,
    ControlSessionRequest,
    ControlSessionResponse,
    ControlSnapshot,
    ManualTakeRequest,
    ModeCommandRequest,
    RenderAckRequest,
    RenderReconcileRequest,
)
from cue_api.readiness import ReadinessError, ReadinessStore, ReceiverReadiness


class ControlHub:
    def __init__(self) -> None:
        self._connections: dict[str, dict[ControlRole, set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )

    def connect(self, event_id: str, role: ControlRole, socket: WebSocket) -> None:
        self._connections[event_id][role].add(socket)

    def disconnect(self, event_id: str, role: ControlRole, socket: WebSocket) -> None:
        self._connections[event_id][role].discard(socket)

    async def broadcast(
        self,
        event_id: str,
        payload: dict[str, object],
        *,
        roles: tuple[ControlRole, ...] = (ControlRole.DIRECTOR, ControlRole.OBSERVER),
    ) -> None:
        for role in roles:
            for socket in tuple(self._connections[event_id][role]):
                try:
                    await socket.send_json(payload)
                except (RuntimeError, WebSocketDisconnect):
                    self.disconnect(event_id, role, socket)

    async def close_event(self, event_id: str, *, code: int = 1000) -> int:
        sockets = [
            socket
            for role_sockets in self._connections.get(event_id, {}).values()
            for socket in tuple(role_sockets)
        ]
        for socket in sockets:
            try:
                await socket.close(code=code)
            except RuntimeError:
                pass
        self._connections.pop(event_id, None)
        return len(sockets)


def _control_http_error(error: ControlError) -> HTTPException:
    code_to_status = {
        "EVENT_ENDED": status.HTTP_410_GONE,
        "INVALID_SESSION": status.HTTP_401_UNAUTHORIZED,
        "SESSION_EXPIRED": status.HTTP_401_UNAUTHORIZED,
    }
    return HTTPException(
        status_code=code_to_status.get(error.code, status.HTTP_409_CONFLICT),
        detail={"code": error.code, "message": str(error)},
    )


def build_control_router(
    store: ControlStore,
    sessions: ControlSessionStore,
    hub: ControlHub,
    readiness: ReadinessStore,
    require_active_event: Callable[[str], None],
    require_producer: Callable[[str | None], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/events/{event_id}", tags=["control"])

    @router.post("/control-sessions", response_model=ControlSessionResponse)
    async def issue_control_session(
        event_id: str,
        payload: ControlSessionRequest,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ControlSessionResponse:
        require_producer(x_cue_producer_secret)
        require_active_event(event_id)
        token, ttl = sessions.issue(event_id, payload.role)
        return ControlSessionResponse(token=token, role=payload.role, expires_in_seconds=ttl)

    @router.get("/control-state", response_model=ControlSnapshot)
    async def control_state(
        event_id: str,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ControlSnapshot:
        require_producer(x_cue_producer_secret)
        return store.snapshot(event_id)

    @router.get("/control-metrics", response_model=ControlLatencyMetrics)
    async def control_metrics(
        event_id: str,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ControlLatencyMetrics:
        require_producer(x_cue_producer_secret)
        store.snapshot(event_id)
        return store.latency_metrics(event_id)

    @router.get("/readiness", response_model=ReceiverReadiness)
    async def receiver_readiness(
        event_id: str,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ReceiverReadiness:
        require_producer(x_cue_producer_secret)
        report = readiness.current(event_id)
        if report is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No readiness report")
        return report

    @router.post("/mode", response_model=ControlMutationResponse)
    async def set_mode(
        event_id: str,
        payload: ModeCommandRequest,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ControlMutationResponse:
        require_producer(x_cue_producer_secret)
        try:
            result = store.set_mode(
                event_id,
                mode=payload.mode,
                expected_revision=payload.expected_revision,
                idempotency_key=payload.idempotency_key,
            )
        except ControlError as error:
            raise _control_http_error(error) from error
        await hub.broadcast(
            event_id,
            {"type": "control.state", "state": result.state.model_dump(mode="json", by_alias=True)},
        )
        return result

    @router.post("/take", response_model=ControlMutationResponse)
    async def manual_take(
        event_id: str,
        payload: ManualTakeRequest,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ControlMutationResponse:
        require_producer(x_cue_producer_secret)
        try:
            result = store.manual_take(
                event_id,
                camera_id=payload.camera_id,
                stream_epoch=payload.stream_epoch,
                expected_revision=payload.expected_revision,
                idempotency_key=payload.idempotency_key,
                reason_code=payload.reason_code,
            )
        except ControlError as error:
            raise _control_http_error(error) from error
        assert result.render_command is not None
        await hub.broadcast(
            event_id,
            {
                "type": "render.command",
                "command": result.render_command.model_dump(mode="json", by_alias=True),
            },
            roles=(ControlRole.DIRECTOR,),
        )
        await hub.broadcast(
            event_id,
            {"type": "control.state", "state": result.state.model_dump(mode="json", by_alias=True)},
        )
        return result

    return router


def build_control_websocket(
    store: ControlStore,
    sessions: ControlSessionStore,
    hub: ControlHub,
    readiness: ReadinessStore,
):
    async def control_socket(websocket: WebSocket, event_id: str) -> None:
        await websocket.accept()
        role: ControlRole | None = None
        try:
            auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
            if auth_message.get("type") != "control.authenticate":
                await websocket.send_json(
                    {
                        "type": "control.error",
                        "code": "AUTH_REQUIRED",
                        "message": "authenticate first",
                    }
                )
                await websocket.close(code=1008)
                return
            session = sessions.validate(str(auth_message.get("token", "")), event_id)
            role = session.role
            hub.connect(event_id, role, websocket)
            await websocket.send_json(
                {"type": "control.authenticated", "role": role.value, "eventId": event_id}
            )
            await websocket.send_json(
                {
                    "type": "control.state",
                    "state": store.snapshot(event_id).model_dump(mode="json", by_alias=True),
                }
            )

            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "control.ping":
                    await websocket.send_json({"type": "control.pong"})
                    continue
                if message_type not in (
                    "render.ack",
                    "render.reconcile",
                    "receiver.readiness",
                ):
                    await websocket.send_json({"type": "control.error", "code": "UNKNOWN_MESSAGE"})
                    continue
                if role is not ControlRole.DIRECTOR:
                    await websocket.send_json(
                        {"type": "control.error", "code": "OBSERVER_READ_ONLY"}
                    )
                    continue
                if store.snapshot(event_id).mode.value == "ENDED":
                    await websocket.send_json(
                        {"type": "control.error", "code": "EVENT_ENDED"}
                    )
                    continue
                try:
                    if message_type == "render.ack":
                        acknowledgement = RenderAckRequest.model_validate(message.get("ack"))
                        state = store.acknowledge(event_id, acknowledgement)
                    elif message_type == "render.reconcile":
                        report = RenderReconcileRequest.model_validate(message.get("report"))
                        state = store.reconcile(event_id, report)
                    else:
                        readiness_report = ReceiverReadiness.model_validate(
                            message.get("readiness")
                        )
                        readiness.ingest(
                            event_id,
                            readiness_report,
                            received_at_ms=round(time.monotonic() * 1000),
                        )
                        await hub.broadcast(
                            event_id,
                            {
                                "type": "receiver.readiness",
                                "readiness": readiness_report.model_dump(
                                    mode="json", by_alias=True
                                ),
                            },
                        )
                        continue
                except ValidationError as error:
                    await websocket.send_json(
                        {
                            "type": "control.error",
                            "code": "INVALID_CONTROL_MESSAGE",
                            "message": str(error),
                        }
                    )
                    continue
                except ControlError as error:
                    await websocket.send_json(
                        {"type": "control.error", "code": error.code, "message": str(error)}
                    )
                    continue
                except ReadinessError as error:
                    await websocket.send_json(
                        {"type": "control.error", "code": error.code, "message": str(error)}
                    )
                    continue
                await hub.broadcast(
                    event_id,
                    {
                        "type": "control.state",
                        "state": state.model_dump(mode="json", by_alias=True),
                    },
                )
        except ControlError as error:
            if role is None:
                try:
                    await websocket.send_json(
                        {"type": "control.error", "code": error.code, "message": str(error)}
                    )
                    await websocket.close(code=1008)
                except RuntimeError:
                    pass
        except (TimeoutError, WebSocketDisconnect):
            if role is None:
                try:
                    await websocket.close(code=1008)
                except RuntimeError:
                    pass
        finally:
            if role is not None:
                hub.disconnect(event_id, role, websocket)

    return control_socket
