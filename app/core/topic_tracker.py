from __future__ import annotations

import time

from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage
from app.core.risk_detector import detect_risk


class TopicTracker:
    def __init__(self, *, active_window_seconds: int = 300) -> None:
        self.active_window_seconds = active_window_seconds

    def assign_topic(self, message: BotMessage, state: GroupState) -> TopicState:
        if message.reply_to:
            topic_id = state.message_topic_map.get(message.reply_to)
            if topic_id and topic_id in state.topics:
                topic = state.topics[topic_id]
                self._update_topic(topic, message, state)
                return topic

        active_topics = self._active_topics(state)
        if len(active_topics) == 1:
            topic = active_topics[0]
            self._update_topic(topic, message, state)
            return topic

        matched_topic = self._find_similar_topic(message, active_topics)
        if matched_topic is not None:
            self._update_topic(matched_topic, message, state)
            return matched_topic

        topic = self._create_topic(message, state)
        self._update_topic(topic, message, state)
        return topic

    def _active_topics(self, state: GroupState) -> list[TopicState]:
        now = time.time()
        return [
            topic
            for topic in state.topics.values()
            if now - topic.last_active_at <= self.active_window_seconds
        ]

    def _find_similar_topic(
        self,
        message: BotMessage,
        topics: list[TopicState],
    ) -> TopicState | None:
        message_tokens = _tokens(message.text)
        if not message_tokens:
            return None

        best_topic: TopicState | None = None
        best_score = 0
        for topic in topics:
            haystack = " ".join(
                [topic.title, topic.summary]
                + [item.text for item in topic.last_messages[-5:]]
            )
            score = len(message_tokens & _tokens(haystack))
            if score > best_score:
                best_score = score
                best_topic = topic

        return best_topic if best_score >= 2 else None

    def _create_topic(self, message: BotMessage, state: GroupState) -> TopicState:
        topic_id = f"topic_{len(state.topics) + 1}"
        title = message.text[:24] or "新话题"
        topic = TopicState(
            topic_id=topic_id,
            title=title,
            summary=message.text[:120],
            last_active_at=time.time(),
        )
        state.topics[topic_id] = topic
        return topic

    def _update_topic(
        self,
        topic: TopicState,
        message: BotMessage,
        state: GroupState,
    ) -> None:
        state.record_topic_message(topic, message)
        recent_text = " / ".join(item.text for item in topic.last_messages[-4:])
        topic.summary = recent_text[:240]
        topic.risk_level = detect_risk(recent_text)


def _tokens(text: str) -> set[str]:
    normalized = "".join(
        char.lower() if char.isalnum() or "\u4e00" <= char <= "\u9fff" else " "
        for char in text
    )
    return {
        token
        for token in normalized.split()
        if len(token) >= 2 or any("\u4e00" <= char <= "\u9fff" for char in token)
    }
