from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from simagentplg import MethodToolHandler, StepOutcome

from app.core.message import BotMessage
from app.core.topic_store import TopicStore


LIST_RECENT_TOPICS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_recent_topics",
        "description": "List recent active topics in a QQ group. summary is distilled; history is recent raw chat text.",
        "parameters": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["group_id", "limit"],
        },
    },
}

GET_TOPIC_MESSAGES_TOOL = {
    "type": "function",
    "function": {
        "name": "get_topic_messages",
        "description": "Get recent messages assigned to a topic.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["topic_id", "limit"],
        },
    },
}

CREATE_TOPIC_TOOL = {
    "type": "function",
    "function": {
        "name": "create_topic",
        "description": "Create a new topic in a QQ group. summary should be a short initial distilled description, not raw history.",
        "parameters": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["group_id", "title", "summary"],
        },
    },
}

ASSIGN_MESSAGE_TO_TOPIC_TOOL = {
    "type": "function",
    "function": {
        "name": "assign_message_to_topic",
        "description": "Assign the current message to an existing topic. This finishes topic classification.",
        "parameters": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "message_id": {"type": "string"},
                "topic_id": {"type": "integer"},
                "msg": {"type": "string"},
            },
            "required": ["group_id", "message_id", "topic_id", "msg"],
        },
    },
}

UPDATE_TOPIC_SUMMARY_TOOL = {
    "type": "function",
    "function": {
        "name": "update_topic_summary",
        "description": "Update a topic summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "summary": {"type": "string"},
            },
            "required": ["topic_id", "summary"],
        },
    },
}


class TopicToolHandler(MethodToolHandler):
    def __init__(self, store: TopicStore) -> None:
        super().__init__(
            (
                LIST_RECENT_TOPICS_TOOL,
                GET_TOPIC_MESSAGES_TOOL,
                CREATE_TOPIC_TOOL,
                ASSIGN_MESSAGE_TO_TOPIC_TOOL,
                UPDATE_TOPIC_SUMMARY_TOOL,
            )
        )
        self.store = store
        self.current_message: BotMessage | None = None
        self.assigned_topic_id: int | None = None

    def begin_turn(self, message: BotMessage) -> None:
        self.current_message = message
        self.assigned_topic_id = None

    async def do_list_recent_topics(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        group_id = int(arguments.get("group_id", 0))
        limit = _limit(arguments.get("limit"), default=10, maximum=20)
        return StepOutcome(self.store.list_recent_topics(group_id, limit=limit))

    async def do_get_topic_messages(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        topic_id = int(arguments.get("topic_id", 0))
        limit = _limit(arguments.get("limit"), default=5, maximum=20)
        return StepOutcome(self.store.get_topic_messages(topic_id, limit=limit))

    async def do_create_topic(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        topic = self.store.create_topic(
            group_id=int(arguments.get("group_id", 0)),
            title=str(arguments.get("title", "")),
            summary=str(arguments.get("summary", "")),
        )
        return StepOutcome(topic)

    async def do_assign_message_to_topic(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        message = self._require_message()
        message_id = str(arguments.get("message_id", ""))
        if message_id != message.message_id:
            return StepOutcome(
                {
                    "status": "error",
                    "error": "message_id must be the current message_id",
                    "current_message_id": message.message_id,
                }
            )

        topic_id = int(arguments.get("topic_id", 0))
        topic = self.store.assign_message_to_topic(
            group_id=int(arguments.get("group_id", message.group_id)),
            message=message,
            topic_id=topic_id,
            text=str(arguments.get("msg", message.text)),
        )
        self.assigned_topic_id = int(topic["id"])
        return StepOutcome(
            {"status": "assigned", "topic": topic},
            should_exit=True,
        )

    async def do_update_topic_summary(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        topic = self.store.update_topic_summary(
            topic_id=int(arguments.get("topic_id", 0)),
            summary=str(arguments.get("summary", "")),
        )
        return StepOutcome(topic)

    def _require_message(self) -> BotMessage:
        if self.current_message is None:
            raise RuntimeError("begin_turn() must be called before topic tools")
        return self.current_message


class TopicSummaryToolHandler(MethodToolHandler):
    def __init__(self, store: TopicStore) -> None:
        super().__init__((UPDATE_TOPIC_SUMMARY_TOOL,))
        self.store = store

    async def do_update_topic_summary(
        self,
        arguments: Mapping[str, Any],
    ) -> StepOutcome:
        topic = self.store.update_topic_summary(
            topic_id=int(arguments.get("topic_id", 0)),
            summary=str(arguments.get("summary", "")),
        )
        return StepOutcome(topic, should_exit=True)


def _limit(value: Any, *, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, number))
