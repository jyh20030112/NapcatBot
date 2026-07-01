from __future__ import annotations

import logging
from typing import Any

from app.core.context_builder import ContextBuilder
from app.core.decision_postcheck import post_check_decision
from app.core.group_state import GroupState
from app.core.json_logging import log_json
from app.core.message import normalize_group_message
from app.services.topic_agent_service import TopicAgentService
from app.services.reply_agent_service import NapcatReplyAgent
from app.services.decision_agent_service import DecisionService

logger = logging.getLogger(__name__)


class GroupMessageHandler:
    def __init__(
        self,
        *,
        bot_id: int,
        bot_name: str,
        agent: NapcatReplyAgent,
    ) -> None:
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.agent = agent
        self.context_builder = ContextBuilder(bot_name=bot_name)
        self.topic_agent = TopicAgentService(
            context_builder=self.context_builder,
        )
        self.decision_service = DecisionService(
            context_builder=self.context_builder,
        )
        self.group_states: dict[int, GroupState] = {}

    async def handle_event(self, event: dict[str, Any]) -> None:
        message = normalize_group_message(
            event,
            bot_id=self.bot_id,
            bot_name=self.bot_name,
        )
        if message is None:
            log_json(
                logger,
                logging.DEBUG,
                "napcat_event_ignored",
                post_type=event.get("post_type"),
                message_type=event.get("message_type"),
                group_id=event.get("group_id"),
                user_id=event.get("user_id"),
                message_id=event.get("message_id"),
            )
            return

        log_json(
            logger,
            logging.INFO,
            "group_message",
            group_id=message.group_id,
            user_id=message.user_id,
            message_id=message.message_id,
            sender=message.nickname,
            role=_sender_field(event, "role"),
            segments=_segment_types(event.get("message")) or ["text"],
            at_bot=message.is_at_bot,
            mentions_bot_name=message.mentions_bot_name,
            reply_to=message.reply_to,
            text_len=len(message.text),
            text=_preview(message.text),
        )

        state = self.group_states.setdefault(
            message.group_id,
            GroupState(group_id=message.group_id),
        )
        state.add_message(message)
        known_topics = set(state.topics)
        topic = await self.topic_agent.assign_topic(message, state)
        log_json(
            logger,
            logging.INFO,
            "topic_assigned",
            group_id=message.group_id,
            message_id=message.message_id,
            topic_id=topic.topic_id,
            new_topic=topic.topic_id not in known_topics,
            risk=topic.risk_level,
            bot_replied_count=topic.bot_replied_count,
            participants=len(topic.participants),
            summary=_preview(topic.summary),
        )
        decision = await self.decision_service.decide(
            message=message,
            topic=topic,
            state=state,
        )
        log_json(
            logger,
            logging.INFO,
            "decision_raw",
            group_id=message.group_id,
            message_id=message.message_id,
            topic_id=decision.topic_id,
            should_reply=decision.should_reply,
            intent=decision.reply_intent,
            style=decision.reply_style,
            target=decision.reply_target,
            risk=decision.risk_level,
            confidence=round(decision.confidence, 2),
            reason=_preview(decision.reason),
        )
        checked_decision = post_check_decision(
            decision,
            message=message,
            topic=topic,
            state=state,
        )
        if checked_decision != decision:
            log_json(
                logger,
                logging.INFO,
                "decision_postcheck_changed",
                group_id=message.group_id,
                message_id=message.message_id,
                topic_id=topic.topic_id,
                before={
                    "should_reply": decision.should_reply,
                    "intent": decision.reply_intent,
                    "confidence": round(decision.confidence, 2),
                },
                after={
                    "should_reply": checked_decision.should_reply,
                    "intent": checked_decision.reply_intent,
                    "confidence": round(checked_decision.confidence, 2),
                    "reason": _preview(checked_decision.reason),
                },
            )
        decision = checked_decision
        task = self.context_builder.build_action_task(
            message=message,
            topic=topic,
            state=state,
            decision=decision,
        )
        await self.agent.handle_message(
            task=task,
            message=message,
            topic=topic,
            state=state,
            decision=decision,
        )

    async def shutdown(self) -> None:
        await self.decision_service.shutdown()
        await self.topic_agent.shutdown()


def _segment_types(message: Any) -> list[str]:
    if isinstance(message, list):
        return [
            str(segment.get("type"))
            for segment in message
            if isinstance(segment, dict) and segment.get("type")
        ]
    return []


def _sender_field(event: dict[str, Any], field: str) -> Any:
    sender = event.get("sender")
    if not isinstance(sender, dict):
        return None
    return sender.get(field)


def _preview(text: str, *, limit: int = 80) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
