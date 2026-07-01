from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, Protocol

from simagentplg import MethodToolHandler, StepOutcome

from app.core.json_logging import log_json
from app.core.reply import clean_reply

logger = logging.getLogger(__name__)


class NapcatActionSender(Protocol):
    async def send_action(
        self,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a OneBot action through NapCat."""


SKIP_REPLY_TOOL = {
    "type": "function",
    "function": {
        "name": "skip_reply",
        "description": "Decide not to reply to the current group message.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short reason for staying silent.",
                }
            },
            "required": ["reason"],
        },
    },
}

SEND_MSG_TOOL = {
    "type": "function",
    "function": {
        "name": "send_msg",
        "description": "Send a plain text message to the current QQ group.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Natural short group-chat reply.",
                }
            },
            "required": ["message"],
        },
    },
}

SEND_AT_MSG_TOOL = {
    "type": "function",
    "function": {
        "name": "send_at_msg",
        "description": "Mention a QQ user in the current group and send text.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "QQ user id to mention.",
                },
                "message": {
                    "type": "string",
                    "description": "Natural short reply after the mention.",
                },
            },
            "required": ["user_id", "message"],
        },
    },
}


class NapcatActionToolHandler(MethodToolHandler):
    def __init__(self, sender: NapcatActionSender) -> None:
        super().__init__((SKIP_REPLY_TOOL, SEND_MSG_TOOL, SEND_AT_MSG_TOOL))
        self.sender = sender
        self.current_group_id: int | None = None
        self.sent_messages: list[str] = []

    def begin_turn(self, *, group_id: int) -> None:
        self.current_group_id = group_id
        self.sent_messages = []

    async def do_skip_reply(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        log_json(
            logger,
            logging.INFO,
            "qq_action_skip_reply",
            group_id=self.current_group_id,
            reason=_preview(str(arguments.get("reason", ""))),
        )
        return StepOutcome(
            {
                "status": "skipped",
                "reason": str(arguments.get("reason", ""))[:120],
            },
            should_exit=True,
        )

    async def do_send_msg(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        group_id = self._require_group_id()
        message = clean_reply(str(arguments.get("message", "")))
        if not message:
            log_json(
                logger,
                logging.WARNING,
                "qq_action_send_msg_rejected",
                group_id=group_id,
                reason="empty_message",
            )
            return StepOutcome(
                {"status": "error", "error": "message must not be empty"}
            )

        log_json(
            logger,
            logging.INFO,
            "qq_action_send_msg",
            group_id=group_id,
            message_len=len(message),
            message=_preview(message),
        )
        result = await self.sender.send_action(
            "send_group_msg",
            {
                "group_id": str(group_id),
                "message": message,
                "auto_escape": False,
            },
        )
        self.sent_messages.append(message)
        return StepOutcome(
            {"status": "sent", "tool": "send_msg", "message": message, "raw": result},
            should_exit=True,
        )

    async def do_send_at_msg(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        group_id = self._require_group_id()
        user_id = arguments.get("user_id")
        try:
            user_id = int(user_id)  # ty:ignore[invalid-argument-type]
        except (TypeError, ValueError):
            log_json(
                logger,
                logging.WARNING,
                "qq_action_send_at_msg_rejected",
                group_id=group_id,
                user_id=arguments.get("user_id"),
                reason="invalid_user_id",
            )
            return StepOutcome(
                {"status": "error", "error": "user_id must be an integer"}
            )

        message = clean_reply(str(arguments.get("message", "")))
        if not message:
            log_json(
                logger,
                logging.WARNING,
                "qq_action_send_at_msg_rejected",
                group_id=group_id,
                user_id=user_id,
                reason="empty_message",
            )
            return StepOutcome(
                {"status": "error", "error": "message must not be empty"}
            )

        log_json(
            logger,
            logging.INFO,
            "qq_action_send_at_msg",
            group_id=group_id,
            user_id=user_id,
            message_len=len(message),
            message=_preview(message),
        )
        segments = [
            {"type": "at", "data": {"qq": str(user_id)}},
            {"type": "text", "data": {"text": f" {message}"}},
        ]
        result = await self.sender.send_action(
            "send_group_msg",
            {
                "group_id": str(group_id),
                "message": segments,
                "auto_escape": False,
            },
        )
        recorded = f"@{user_id} {message}"
        self.sent_messages.append(recorded)
        return StepOutcome(
            {
                "status": "sent",
                "tool": "send_at_msg",
                "user_id": user_id,
                "message": message,
                "raw": result,
            },
            should_exit=True,
        )

    def _require_group_id(self) -> int:
        if self.current_group_id is None:
            raise RuntimeError("begin_turn() must be called before QQ actions")
        return self.current_group_id


def _preview(text: str, *, limit: int = 80) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
