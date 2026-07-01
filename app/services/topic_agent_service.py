from __future__ import annotations

import logging
import os
from pathlib import Path

from simagentplg import BaseAgent, ModelConfig

from app.core.context_builder import ContextBuilder
from app.core.group_state import GroupState, TopicState
from app.core.json_logging import log_json
from app.core.message import BotMessage
from app.core.reply import detect_risk
from app.core.topic_store import TopicStore
from app.llms_tools.napcat_topic_tools import TopicToolHandler

logger = logging.getLogger(__name__)


TOPIC_SYSTEM_PROMPT = """
你是 QQ 群聊的话题归类 Agent。

你的唯一任务是判断当前消息属于已有话题，还是应该创建新话题。你不负责聊天回复。

规则：
1. 必须通过工具读取和写入话题。
2. 先调用 list_recent_topics 查看当前群最近话题。
3. 如果 summary 不够判断，可以调用 get_topic_messages 查看某个话题最近消息。
4. 如果当前消息明显延续某个话题，调用 assign_message_to_topic。
5. 如果当前消息开启了新话题，先调用 create_topic，再调用 assign_message_to_topic。
6. assign_message_to_topic 是最终动作，完成后不要再输出普通文本。
7. 不要把无关消息硬归到唯一活跃话题；不确定时创建新话题。
""".strip()


class TopicAgentService:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        store: TopicStore | None = None,
        config: ModelConfig | None = None,
        max_steps: int = 8,
    ) -> None:
        self.context_builder = context_builder
        self.store = store or TopicStore(_topic_db_path())
        self.tool_handler = TopicToolHandler(self.store)
        self.agent = BaseAgent(
            config=config or ModelConfig.from_env(),
            agent_id="napcat_topic_classifier",
            system_prompt=TOPIC_SYSTEM_PROMPT,
            handlers=[self.tool_handler],
            enable_tools=True,
            max_steps=max_steps,
        )

    async def assign_topic(
        self,
        message: BotMessage,
        state: GroupState,
    ) -> TopicState:
        if message.reply_to:
            topic = self.store.get_topic_by_message(
                group_id=message.group_id,
                message_id=message.reply_to,
            )
            if topic is not None:
                assigned = self.store.assign_message_to_topic(
                    group_id=message.group_id,
                    message=message,
                    topic_id=int(topic["id"]),
                )
                log_json(
                    logger,
                    logging.DEBUG,
                    "topic_classified",
                    group_id=message.group_id,
                    message_id=message.message_id,
                    topic_id=assigned["id"],
                    topic_no=assigned["topic_no"],
                    action="assign_by_reply",
                )
                return _sync_topic_state(assigned, message, state)

        self.tool_handler.begin_turn(message)
        task = self.context_builder.build_topic_task(message=message)
        try:
            await self.agent.runtime(task=task)
        except Exception:
            logger.log(
                logging.ERROR,
                "topic_agent_failed",
                exc_info=True,
                extra={"event": "topic_agent_failed", "data": {"group_id": message.group_id, "message_id": message.message_id}},
            )

        if self.tool_handler.assigned_topic_id is None:
            return self._fallback_create_topic(message, state)

        topic = self.store.get_topic(self.tool_handler.assigned_topic_id)
        if topic is None:
            return self._fallback_create_topic(message, state)

        log_json(
            logger,
            logging.DEBUG,
            "topic_classified",
            group_id=message.group_id,
            message_id=message.message_id,
            topic_id=topic["id"],
            topic_no=topic["topic_no"],
            action="assign_by_agent",
        )
        return _sync_topic_state(topic, message, state)

    def _fallback_create_topic(
        self,
        message: BotMessage,
        state: GroupState,
    ) -> TopicState:
        topic = self.store.create_topic(
            group_id=message.group_id,
            title=message.text[:24] or "新话题",
            summary=message.text[:120] or "新话题",
        )
        topic = self.store.assign_message_to_topic(
            group_id=message.group_id,
            message=message,
            topic_id=int(topic["id"]),
        )
        log_json(
            logger,
            logging.WARNING,
            "topic_classified",
            group_id=message.group_id,
            message_id=message.message_id,
            topic_id=topic["id"],
            topic_no=topic["topic_no"],
            action="fallback_create_topic",
        )
        return _sync_topic_state(topic, message, state)

    async def shutdown(self) -> None:
        await self.agent.shutdown()



def _sync_topic_state(
    topic_row: dict[str, object],
    message: BotMessage,
    state: GroupState,
) -> TopicState:
    topic_id = str(topic_row["topic_no"])
    topic = state.topics.get(topic_id)
    if topic is None:
        topic = TopicState(
            topic_id=topic_id,
            title=str(topic_row["title"]),
            summary=str(topic_row["summary"]),
            last_active_at=float(topic_row["updated_at"]),  # ty:ignore[invalid-argument-type]
        )
        state.topics[topic_id] = topic
    else:
        topic.title = str(topic_row["title"])
        topic.summary = str(topic_row["summary"])
        topic.last_active_at = float(topic_row["updated_at"])  # ty:ignore[invalid-argument-type]

    state.record_topic_message(topic, message)
    recent_text = " / ".join(item.text for item in topic.last_messages[-20:])
    topic.summary = recent_text[:] or topic.summary
    topic.risk_level = detect_risk(recent_text)
    return topic


def _topic_db_path() -> Path:
    return Path(os.getenv("TOPIC_DB_PATH", "data/topics.sqlite3"))
