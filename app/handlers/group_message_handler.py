from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.context_builder import ContextBuilder
from app.core.group_state import GroupState
from app.core.json_logging import log_json
from app.core.message import normalize_group_message
from app.llms_tools.napcat_topic_tools import TopicActionSender
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
        hide: bool = False,
        owner_name: str = "",
        owner_id: int = 0,
        topic_sender: TopicActionSender | None = None,
    ) -> None:
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.agent = agent
        self.hide = hide
        self.owner_name = owner_name
        self.owner_id = owner_id
        self.context_builder = ContextBuilder(bot_name=bot_name)
        self.topic_agent = TopicAgentService(
            context_builder=self.context_builder,
            bot_name=bot_name,
            bot_id=bot_id,
            owner_name=owner_name,
            owner_id=owner_id,
            sender=topic_sender,
        )
        self.decision_service = DecisionService(
            context_builder=self.context_builder,
            bot_name=bot_name,
            bot_id=bot_id,
            owner_name=owner_name,
            owner_id=owner_id,
        )
        self.group_states: dict[int, GroupState] = {}
        self._reload_lock = asyncio.Lock()

    async def handle_event(self, event: dict[str, Any]) -> None:
        async with self._reload_lock:
            await self._handle_event_locked(event)

    async def _handle_event_locked(self, event: dict[str, Any]) -> None:
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
        analysis = await self.decision_service.analyze(
            message=message,
            topic=topic,
            state=state,
        )
        log_json(
            logger,
            logging.INFO,
            "message_analysis",
            group_id=message.group_id,
            message_id=message.message_id,
            topic_id=analysis.topic_id,
            intent=analysis.reply_intent,
            risk=analysis.risk_level,
            confidence=round(analysis.confidence, 2),
            analysis=_preview(analysis.reason, limit=800),
        )

        if self.hide:
            log_json(
                logger,
                logging.DEBUG,
                "hide_mode_reply_dry_run",
                group_id=message.group_id,
                message_id=message.message_id,
                topic_id=topic.topic_id,
                intent=analysis.reply_intent,
                risk=analysis.risk_level,
                confidence=round(analysis.confidence, 2),
                analysis=_preview(analysis.reason, limit=800),
            )

        task = self.context_builder.build_action_task(
            message=message,
            topic=topic,
            state=state,
            analysis=analysis,
        )
        await self.agent.handle_message(
            task=task,
            message=message,
            topic=topic,
            state=state,
            analysis=analysis,
        )

    async def reload_runtime(
        self,
        *,
        bot_id: int,
        bot_name: str,
        agent: NapcatReplyAgent,
        hide: bool = False,
        owner_name: str = "",
        owner_id: int = 0,
    ) -> None:
        async with self._reload_lock:
            old_agent = self.agent
            old_topic_agent = self.topic_agent
            old_decision_service = self.decision_service

            self.bot_id = bot_id
            self.bot_name = bot_name
            self.agent = agent
            self.hide = hide
            self.owner_name = owner_name
            self.owner_id = owner_id
            self.context_builder = ContextBuilder(bot_name=bot_name)
            self.topic_agent = TopicAgentService(
                context_builder=self.context_builder,
                bot_name=bot_name,
                bot_id=bot_id,
                owner_name=owner_name,
                owner_id=owner_id,
            )
            self.decision_service = DecisionService(
                context_builder=self.context_builder,
                bot_name=bot_name,
                bot_id=bot_id,
                owner_name=owner_name,
                owner_id=owner_id,
            )

            await old_decision_service.shutdown()
            await old_topic_agent.shutdown()
            await old_agent.shutdown()

            log_json(
                logger,
                logging.INFO,
                "runtime_reloaded",
                bot_id=bot_id,
                bot_name=bot_name,
                groups=len(self.group_states),
                hide=hide,
            )

    async def shutdown(self) -> None:
        await self.decision_service.shutdown()
        await self.topic_agent.shutdown()
        await self.agent.shutdown()


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
