import json
import random
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from simagentplg import MethodToolHandler, StepOutcome

type MessageSegment = dict[str, Any]
type MessageContent = str | list[MessageSegment]


def clean_reply_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)

    text = text.strip()
    text = text.replace("```", "")

    bracket_pairs = [
        ("（", "）"),
        ("(", ")"),
        ("【", "】"),
    ]

    for left, right in bracket_pairs:
        while left in text and right in text:
            start = text.find(left)
            end = text.find(right, start + 1)

            if end == -1:
                break

            inner = text[start + 1:end]

            if len(inner) <= 30:
                text = text[:start] + text[end + 1:]
            else:
                break

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not lines:
        return "嗯"

    text = " ".join(lines[:2]).strip()
    text = re.sub(r"^(姜亦衡|小姜|义恒|不知名小卒)\s*[：:]\s*", "", text).strip()

    if len(text) > 45:
        text = text[:45].rstrip("，。,.、 ") + "…"

    return text or "嗯"


def build_text_segment(text: str) -> MessageSegment:
    return {"type": "text", "data": {"text": text}}


def build_face_segment(face_id: str) -> MessageSegment:
    return {"type": "face", "data": {"id": str(face_id)}}


def build_private_msg_params(
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> dict[str, Any]:
    return {
        "message": message,
        "auto_escape": auto_escape,
        "message_type": "private",
        "user_id": str(data.get("user_id", "")),
    }


def build_group_msg_params(
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> dict[str, Any]:
    return {
        "group_id": str(data.get("group_id", "")),
        "message": message,
        "auto_escape": auto_escape,
    }


def build_private_msg_action(
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> dict[str, Any]:
    return {
        "action": "send_msg",
        "params": build_private_msg_params(data, message, auto_escape=auto_escape),
    }


def build_group_msg_action(
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> dict[str, Any]:
    return {
        "action": "send_group_msg",
        "params": build_group_msg_params(data, message, auto_escape=auto_escape),
    }


async def send_action(
    websocket: Any,
    action: dict[str, Any],
    *,
    log_event: Callable[..., None] | None = None,
) -> None:
    action["echo"] = f"echo-{datetime.now().timestamp()}-{random.randint(1000, 9999)}"
    await websocket.send(json.dumps(action, ensure_ascii=False))
    if log_event is not None:
        log_event("已发送 action", action=action)


async def send_message(
    websocket: Any,
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
    log_event: Callable[..., None] | None = None,
) -> None:
    if data.get("message_type") == "group":
        reply = build_group_msg_action(data, message, auto_escape=auto_escape)
    else:
        reply = build_private_msg_action(data, message, auto_escape=auto_escape)
    await send_action(websocket, reply, log_event=log_event)


SEND_QQ_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "send_qq_message",
        "description": (
            "向当前 QQ 私聊或群聊发送一条回复，并结束本轮对话。"
            "私聊使用 send_msg，群聊使用 send_group_msg。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要发送的短文本回复。",
                },
                "face_id": {
                    "type": "string",
                    "description": "可选 QQ 自带表情 ID，例如 14 表示微笑。",
                },
                "auto_escape": {
                    "type": "boolean",
                    "description": "是否按纯文本发送，通常保持 false。",
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
}


class NapCatQQHandler(MethodToolHandler):
    """Expose the current NapCat message target as an agent tool."""

    def __init__(self, *, log_event: Callable[..., None] | None = None) -> None:
        super().__init__((SEND_QQ_MESSAGE_TOOL,))
        self.websocket: Any | None = None
        self.event: dict[str, Any] | None = None
        self.log_event = log_event

    def set_context(self, websocket: Any, event: dict[str, Any]) -> None:
        self.websocket = websocket
        self.event = event

    async def do_send_qq_message(self, arguments: dict[str, Any]) -> StepOutcome:
        if self.websocket is None or self.event is None:
            return StepOutcome(
                {"status": "error", "error": "napcat context is not ready"},
                should_exit=True,
            )

        text = clean_reply_text(str(arguments.get("text", "")))
        face_id = str(arguments.get("face_id", "") or "").strip()
        auto_escape = bool(arguments.get("auto_escape", False))

        message: MessageContent
        if face_id:
            segments = []
            if text:
                segments.append(build_text_segment(text))
            segments.append(build_face_segment(face_id))
            message = segments
        else:
            message = text or "嗯"

        await send_message(
            self.websocket,
            self.event,
            message,
            auto_escape=auto_escape,
            log_event=self.log_event,
        )
        return StepOutcome(
            {"status": "success", "message": message},
            should_exit=True,
        )
