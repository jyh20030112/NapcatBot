from dataclasses import dataclass, field
import time
from typing import Literal

from app.core.reply import ReplyDecision
from app.core.message import BotMessage


@dataclass(slots=True)
class TopicState:
    topic_id: str
    title: str
    summary: str
    history: str = ""
    participants: set[int] = field(default_factory=set)
    last_messages: list[BotMessage] = field(default_factory=list)
    last_active_at: float = 0
    risk_level: Literal["normal", "sensitive", "conflict"] = "normal"
    bot_replied_count: int = 0
    bot_last_reply: str | None = None


@dataclass(slots=True)
class GroupState:
    group_id: int
    recent_messages: list[BotMessage] = field(default_factory=list)
    topics: dict[str, TopicState] = field(default_factory=dict)
    message_topic_map: dict[str, str] = field(default_factory=dict)
    bot_recent_replies: list[str] = field(default_factory=list)
    recent_decisions: list[ReplyDecision] = field(default_factory=list)
    last_bot_reply_at: float = 0

    def add_message(self, message: BotMessage, *, limit: int = 80) -> None:
        self.recent_messages.append(message)
        if len(self.recent_messages) > limit:
            del self.recent_messages[: len(self.recent_messages) - limit]

    def record_topic_message(
        self,
        topic: TopicState,
        message: BotMessage,
        *,
        limit: int = 20,
    ) -> None:
        topic.participants.add(message.user_id)
        topic.last_messages.append(message)
        if len(topic.last_messages) > limit:
            del topic.last_messages[: len(topic.last_messages) - limit]
        topic.last_active_at = time.time()
        if message.message_id:
            self.message_topic_map[message.message_id] = topic.topic_id

    def record_bot_reply(
        self,
        topic_id: str,
        text: str,
        *,
        limit: int = 5,
    ) -> None:
        self.bot_recent_replies.append(text)
        if len(self.bot_recent_replies) > limit:
            del self.bot_recent_replies[: len(self.bot_recent_replies) - limit]
        self.last_bot_reply_at = time.time()
        topic = self.topics.get(topic_id)
        if topic is not None:
            topic.bot_replied_count += 1
            topic.bot_last_reply = text

    def record_decision(
        self,
        decision: ReplyDecision,
        *,
        limit: int = 20,
    ) -> None:
        self.recent_decisions.append(decision)
        if len(self.recent_decisions) > limit:
            del self.recent_decisions[: len(self.recent_decisions) - limit]

    def bot_replied_recently(self, *, seconds: int) -> bool:
        if self.last_bot_reply_at <= 0:
            return False
        return time.time() - self.last_bot_reply_at <= seconds
