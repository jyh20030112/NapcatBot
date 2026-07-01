from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class BotMessage:
    message_id: str
    group_id: int
    user_id: int
    nickname: str
    text: str
    raw: dict[str, Any]
    is_at_bot: bool = False
    reply_to: str | None = None
    reply_to_bot: bool = False
    mentions_bot_name: bool = False
    message_type: Literal["group", "private"] = "group"


def normalize_group_message(
    event: dict[str, Any],
    *,
    bot_id: int,
    bot_name: str,
) -> BotMessage | None:
    if event.get("post_type") != "message":
        return None
    if event.get("message_type") != "group":
        return None

    group_id = _as_int(event.get("group_id"))
    user_id = _as_int(event.get("user_id"))
    if group_id is None or user_id is None:
        return None
    if user_id == bot_id:
        return None

    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    nickname = str(
        sender.get("card")  # ty:ignore[unresolved-attribute]
        or sender.get("nickname")  # ty:ignore[unresolved-attribute]
        or sender.get("user_id")  # ty:ignore[unresolved-attribute]
        or user_id
    )

    text, is_at_bot, reply_to = _extract_text_and_marks(
        event.get("message"),
        bot_id=bot_id,
    )
    text = text.strip()
    if not text and not is_at_bot:
        return None

    return BotMessage(
        message_id=str(event.get("message_id", "")),
        group_id=group_id,
        user_id=user_id,
        nickname=nickname,
        text=text,
        raw=event,
        is_at_bot=is_at_bot,
        reply_to=reply_to,
        mentions_bot_name=bool(bot_name and bot_name in text),
    )


def _extract_text_and_marks(
    message: Any,
    *,
    bot_id: int,
) -> tuple[str, bool, str | None]:
    if isinstance(message, str):
        return message, False, None

    if not isinstance(message, list):
        return str(message or ""), False, None

    parts: list[str] = []
    is_at_bot = False
    reply_to: str | None = None
    for segment in message:
        if not isinstance(segment, dict):
            continue
        segment_type = segment.get("type")
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}

        if segment_type == "text":
            parts.append(str(data.get("text", "")))
        elif segment_type == "at":
            qq = str(data.get("qq", ""))
            if qq == str(bot_id):
                is_at_bot = True
            else:
                parts.append(f"@{qq}")
        elif segment_type == "reply":
            reply_id = data.get("id")
            if reply_id is not None:
                reply_to = str(reply_id)

    return "".join(parts), is_at_bot, reply_to


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
