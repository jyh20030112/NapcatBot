from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from uuid import uuid4

from app.core.json_logging import log_json
from app.handlers.group_message_handler import GroupMessageHandler

logger = logging.getLogger(__name__)


class NapcatWebSocketAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int,
    ) -> None:
        self.host = host
        self.port = port
        self._websocket: Any | None = None
        self._send_lock = asyncio.Lock()
        self._dry_run_actions = False

    def set_action_dry_run(self, enabled: bool) -> None:
        if self._dry_run_actions == enabled:
            return
        self._dry_run_actions = enabled
        log_json(
            logger,
            logging.INFO,
            "napcat_action_dry_run_changed",
            enabled=enabled,
        )

    async def run_forever(self, handler: GroupMessageHandler) -> None:
        import websockets

        async with websockets.serve(
            lambda websocket: self._recv_messages(websocket, handler),
            self.host,
            self.port,
            process_request=self._log_ws_request,
        ):
            log_json(
                logger,
                logging.INFO,
                "napcat_ws_listening",
                host=self.host,
                port=self.port,
                url=f"ws://{self.host}:{self.port}",
            )
            await asyncio.Future()

    async def _recv_messages(
        self,
        websocket: Any,
        handler: GroupMessageHandler,
    ) -> None:
        remote = getattr(websocket, "remote_address", None)
        log_json(logger, logging.DEBUG, "napcat_ws_connected", remote=remote)
        self._websocket = websocket
        try:
            async for raw_payload in websocket:
                event = self._decode_event(raw_payload)
                if event is None:
                    continue
                _log_event_summary(event)
                await handler.handle_event(event)
        finally:
            if self._websocket is websocket:
                self._websocket = None
            log_json(logger, logging.DEBUG, "napcat_ws_disconnected", remote=remote)

    async def _log_ws_request(self, connection: Any, request: Any) -> None:
        log_json(
            logger,
            logging.DEBUG,
            "napcat_ws_handshake",
            remote=getattr(connection, "remote_address", None),
            path=getattr(request, "path", None),
        )
        return None

    async def send_action(
        self,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "action": action,
            "params": params,
            "echo": f"echo-{uuid4().hex}",
        }
        if self._dry_run_actions:
            log_json(
                logger,
                logging.INFO,
                "napcat_action_dry_run",
                action=action,
                echo=payload["echo"],
                group_id=params.get("group_id"),
                message_len=_message_len(params.get("message")),
                params=params,
            )
            return {"status": "dry_run", "echo": payload["echo"]}

        if self._websocket is None:
            raise RuntimeError("NapCat websocket is not connected")

        started_at = time.monotonic()
        async with self._send_lock:
            await self._websocket.send(json.dumps(payload, ensure_ascii=False))
        log_json(
            logger,
            logging.INFO,
            "napcat_action_sent",
            action=action,
            echo=payload["echo"],
            group_id=params.get("group_id"),
            message_len=_message_len(params.get("message")),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
        return {"status": "sent", "echo": payload["echo"]}

    @staticmethod
    def _decode_event(raw_payload: Any) -> dict[str, Any] | None:
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            log_json(
                logger,
                logging.WARNING,
                "napcat_payload_invalid_json",
                payload=_preview(raw_payload),
            )
            return None
        if not isinstance(payload, dict):
            log_json(
                logger,
                logging.WARNING,
                "napcat_payload_not_object",
                payload=_preview(payload),
            )
            return None
        if "post_type" not in payload:
            log_json(
                logger,
                logging.WARNING,
                "napcat_payload_missing_post_type",
                payload=_preview(payload),
            )
            return None
        return payload


def _log_event_summary(event: dict[str, Any]) -> None:
    post_type = event.get("post_type")
    if post_type == "meta_event" and event.get("meta_event_type") == "heartbeat":
        log_json(
            logger,
            logging.DEBUG,
            "napcat_heartbeat",
            self_id=event.get("self_id"),
            time=event.get("time"),
            status=event.get("status"),
            interval=event.get("interval"),
        )
        return

    log_json(
        logger,
        logging.DEBUG,
        "napcat_event",
        post_type=post_type,
        self_id=event.get("self_id"),
        time=event.get("time"),
        message_type=event.get("message_type"),
        sub_type=event.get("sub_type"),
        meta_event_type=event.get("meta_event_type"),
        notice_type=event.get("notice_type"),
        request_type=event.get("request_type"),
        group_id=event.get("group_id"),
        user_id=event.get("user_id"),
        message_id=event.get("message_id"),
        metadata=event.get("metadata"),
        status=event.get("status"),
    )


def _message_len(message: Any) -> int:
    if isinstance(message, str):
        return len(message)
    if isinstance(message, list):
        return sum(_segment_text_len(segment) for segment in message)
    return 0


def _segment_text_len(segment: Any) -> int:
    if not isinstance(segment, dict):
        return 0
    data = segment.get("data")
    if not isinstance(data, dict):
        return 0
    return len(str(data.get("text", "")))


def _preview(value: Any, *, limit: int = 500) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
