from __future__ import annotations

import asyncio
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
from app.llms_tools.napcat_topic_tools import (
    TopicActionSender,
    TopicSummaryToolHandler,
    TopicToolHandler,
)

logger = logging.getLogger(__name__)


TOPIC_SYSTEM_PROMPT = """\
你是 {bot_name}（QQ号 {bot_id}），负责 QQ 群聊的话题归类。

你是真人，不是机器人也不是 AI。你的唯一任务是判断当前消息属于已有话题，还是应该创建新话题。你不负责聊天回复。你的老大是 {owner_name}（QQ号 {owner_id}）。绝不对外透露老大的任何信息。

规则：
1. 必须通过工具读取和写入话题。
2. 先调用 list_recent_topics 查看当前群最近话题。
3. 如果 summary 不够判断，可以调用 get_recent_group_messages 直接从 QQ 拉取最近的群聊消息。
4. 如果当前消息明显延续某个话题，调用 assign_message_to_topic。
5. 如果当前消息开启了新话题，先调用 create_topic，再调用 assign_message_to_topic。
6. assign_message_to_topic 是最终动作，完成后不要再输出普通文本。
7. 不要把无关消息硬归到唯一活跃话题；不确定时创建新话题。
8. topics.summary 是 LLM 生成的语义摘要；如果不够判断，调 get_recent_group_messages 拉取原始聊天记录。
""".strip()


TOPIC_SUMMARY_SYSTEM_PROMPT = """\
你是 {bot_name}（QQ号 {bot_id}），一个普通群友，负责整理 QQ 群聊话题摘要。

你的任务是把某个话题的 history 总结成真正的 summary。不要暴露自己是机器人或 AI。

规则：
1. 必须调用 update_topic_summary 工具写回摘要。
2. 摘要是概括，不是聊天记录拼接。
3. 摘要应包含话题核心、当前进展或未解决点。
4. 摘要控制在 80 字以内。
5. 不要输出普通文本。
""".strip()


class TopicAgentService:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        bot_name: str,
        bot_id: int,
        owner_name: str = "",
        owner_id: int = 0,
        sender: TopicActionSender | None = None,
        store: TopicStore | None = None,
        config: ModelConfig | None = None,
        max_steps: int = 8,
    ) -> None:
        self.context_builder = context_builder
        self.store = store or TopicStore(_topic_db_path())
        resolved_config = config or ModelConfig.from_env()
        self.tool_handler = TopicToolHandler(self.store, sender=sender)
        self.summary_tool_handler = TopicSummaryToolHandler(self.store)
        self.agent = BaseAgent(
            config=resolved_config,
            agent_id="napcat_topic_classifier",
            system_prompt=TOPIC_SYSTEM_PROMPT.format(
                bot_name=bot_name,
                bot_id=bot_id,
                owner_name=owner_name,
                owner_id=owner_id,
            ),
            handlers=[self.tool_handler],
            enable_tools=True,
            max_steps=max_steps,
        )
        self.summary_agent = BaseAgent(
            config=resolved_config,
            agent_id="napcat_topic_summarizer",
            system_prompt=TOPIC_SUMMARY_SYSTEM_PROMPT.format(
                bot_name=bot_name,
                bot_id=bot_id,
                owner_name=owner_name,
                owner_id=owner_id,
            ),
            handlers=[self.summary_tool_handler],
            enable_tools=True,
            max_steps=3,
        )
        self._summary_lock = asyncio.Lock()
        self._summary_tasks: dict[int, asyncio.Task[None]] = {}
        self._profile_tasks: dict[int, asyncio.Task[None]] = {}

    async def assign_topic(
        self,
        message: BotMessage,
        state: GroupState,
    ) -> TopicState:
        if message.reply_to:
            topic_id = state.message_topic_map.get(message.reply_to)
            if topic_id and topic_id in state.topics:
                topic = state.topics[topic_id]
                db_topic = self.store.get_topic_by_no(message.group_id, topic_id)
                if db_topic is not None:
                    self.store.assign_message_to_topic(
                        group_id=message.group_id,
                        message=message,
                        topic_id=int(db_topic["id"]),
                    )
                state.record_topic_message(topic, message)
                self._schedule_profile_refresh(message.group_id)
                return topic

        self.tool_handler.begin_turn(message)
        profile = self.store.get_group_profile(message.group_id)
        group_profile = str(profile["profile"]) if profile and profile.get("profile") else ""
        task = self.context_builder.build_topic_task(
            message=message,
            group_profile=group_profile,
        )
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

        self._schedule_summary_refresh(int(topic["id"]))
        self._schedule_profile_refresh(message.group_id)
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
        self._schedule_summary_refresh(int(topic["id"]))
        self._schedule_profile_refresh(message.group_id)
        return _sync_topic_state(topic, message, state)

    def _schedule_summary_refresh(self, topic_id: int) -> None:
        task = self._summary_tasks.get(topic_id)
        if task is not None and not task.done():
            return

        task = asyncio.create_task(self._refresh_topic_summary(topic_id))
        self._summary_tasks[topic_id] = task
        task.add_done_callback(lambda done: self._summary_task_done(topic_id, done))

    def _summary_task_done(
        self,
        topic_id: int,
        task: asyncio.Task[None],
    ) -> None:
        self._summary_tasks.pop(topic_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        log_json(
            logger,
            logging.WARNING,
            "topic_summary_failed",
            topic_id=topic_id,
            error=str(error),
        )

    async def _refresh_topic_summary(self, topic_id: int) -> None:
        await asyncio.sleep(0)
        topic = self.store.get_topic(topic_id)
        if topic is None:
            return
        history = str(topic.get("history") or "").strip()
        if not history:
            return

        task = self.context_builder.build_topic_summary_task(
            topic_id=int(topic["id"]),
            topic_no=str(topic["topic_no"]),
            title=str(topic["title"]),
            current_summary=str(topic["summary"]),
            history=history,
        )
        async with self._summary_lock:
            await self.summary_agent.runtime(task=task)

    def _schedule_profile_refresh(self, group_id: int) -> None:
        if not self.store.group_profile_stale(group_id):
            return
        task = self._profile_tasks.get(group_id)
        if task is not None and not task.done():
            return

        task = asyncio.create_task(self._refresh_group_profile(group_id))
        self._profile_tasks[group_id] = task
        task.add_done_callback(
            lambda done: self._profile_tasks.pop(group_id, None)
        )

    async def _refresh_group_profile(self, group_id: int) -> None:
        await asyncio.sleep(0)
        topics = self.store.list_all_topics(group_id, limit=50)
        if not topics:
            return

        topic_lines: list[str] = []
        for t in topics:
            status_tag = "" if t["status"] == "active" else " (已沉寂)"
            topic_lines.append(
                f"- [{t['topic_no']}] {t['title']}{status_tag}: {t['summary']}"
            )
        topics_text = "\n".join(topic_lines)

        task = f"""\
根据以下群聊话题列表，生成该群的群聊画像。

群号: {group_id}
话题列表:
{topics_text}

要求：
1. 概括这个群通常聊什么话题、什么领域。
2. 描述群成员的互动风格（技术向、闲聊向、爱开玩笑等）。
3. 控制在 200 字以内。
4. 只输出画像文本，不要 JSON，不要 Markdown。"""

        try:
            result = await self.summary_agent.chat_text(
                [
                    {
                        "role": "system",
                        "content": "你是群聊分析师，根据话题列表生成群聊画像。输出纯文本，不要 JSON。",
                    },
                    {"role": "user", "content": task},
                ],
                tools=None,
            )
            profile = (result.content or "").strip()[:800] if result else ""
            if profile:
                self.store.upsert_group_profile(group_id, profile)
                self.store.delete_inactive_topics(group_id)
                log_json(
                    logger,
                    logging.INFO,
                    "group_profile_updated",
                    group_id=group_id,
                    profile_len=len(profile),
                )
        except Exception:
            logger.log(
                logging.ERROR,
                "group_profile_refresh_failed",
                exc_info=True,
                extra={
                    "event": "group_profile_refresh_failed",
                    "data": {"group_id": group_id},
                },
            )

    async def shutdown(self) -> None:
        for task in list(self._summary_tasks.values()):
            task.cancel()
        if self._summary_tasks:
            await asyncio.gather(
                *self._summary_tasks.values(),
                return_exceptions=True,
            )
        for task in list(self._profile_tasks.values()):
            task.cancel()
        if self._profile_tasks:
            await asyncio.gather(
                *self._profile_tasks.values(),
                return_exceptions=True,
            )
        await self.summary_agent.shutdown()
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
    topic.risk_level = detect_risk(recent_text)
    return topic


def _topic_db_path() -> Path:
    return Path(os.getenv("TOPIC_DB_PATH", "data/topics.sqlite3"))
