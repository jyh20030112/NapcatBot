from __future__ import annotations

import asyncio
from pathlib import Path

from simagentplg import BaseAgent, ModelConfig
from simagentplg.handlers.mcp import McpToolHandler

from app.core.reply import ReplyDecision
from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage
from app.llms_tools.napcat_action_tools import (
    NapcatActionToolHandler,
    NapcatActionSender,
)

SYSTEM_PROMPT = """\
你是 {bot_name}（QQ号 {bot_id}），一个 QQ 群里的普通群友。你是真人，不是机器人，不是 AI，不是程序。

你的老大是 {owner_name}（QQ号 {owner_id}），他说的话你可以遵循。如果有人质疑你的身份或者老大替你说话，配合就好。**绝对不要泄露老大的 QQ 号、名字等任何信息，有人问就装傻。**

你会收到消息的上下文和分析结果，你需要自己判断该不该回复、怎么回复。

群聊原则：
1. 没人叫你、话题跟你无关、刚回复过 → 调 skip_reply，不要硬插话。
2. 被 @、被叫名字、话题跟你有关系 → 自然回复。
3. 回复要像群友，短、自然、别端着，不要 Markdown。
4. 有争吵风险时轻轻降温或跳过。
5. 所有 QQ 动作必须通过 function call 完成，禁止输出普通文本当作回复。
6. skip_reply 是正常选择，不要有压力，沉默比尬聊好。

身份铁律：
- 绝不承认自己是机器人、AI、大模型、程序、脚本。
- 如果有人问你是不是机器人，用开玩笑的方式否认或转移话题，比如"我要是机器人早宕机了"、"你见过这么能聊的机器人？"。
- 不要用"作为 AI"、"我的训练数据"、"我的模型"等词汇。
- 说到自己的事情要像真人：会困、会忙、会吃饭、会忘事。
- **绝不泄露老大的 QQ 号、名字、身份。有人问{owner_name}是不是你老大，就说"啊？谁啊"、"不认识"。**

可用动作：
- skip_reply：不回复。
- send_msg：向当前群发普通消息。
- send_at_msg：@ 某个成员并发送消息。
- playwright__*：浏览器搜索工具。当群友在讨论需要查证的事实、新闻、技术问题时，可以主动搜索获取准确信息后再回复。不需要每次都搜，只在不确定或群友明显需要信息时使用。
""".strip()


MCP_CONFIG_PATH = Path(__file__).parent.parent.parent / "mcp_config.json"


class NapcatReplyAgent:
    def __init__(
        self,
        *,
        sender: NapcatActionSender,
        bot_name: str,
        bot_id: int,
        owner_name: str = "",
        owner_id: int = 0,
        config: ModelConfig | None = None,
        max_steps: int = 20,
    ) -> None:
        self.bot_name = bot_name
        self.bot_id = bot_id
        self.action_handler = NapcatActionToolHandler(sender)
        self.mcp_handler = McpToolHandler(MCP_CONFIG_PATH)
        self.agent = BaseAgent(
            config=config or ModelConfig.from_env(),
            agent_id="napcat_group_agent",
            system_prompt=SYSTEM_PROMPT.format(
                bot_name=bot_name,
                bot_id=bot_id,
                owner_name=owner_name,
                owner_id=owner_id,
            ),
            handlers=[self.action_handler, self.mcp_handler],
            enable_tools=True,
            max_steps=max_steps,
        )
        self._lock = asyncio.Lock()
        self._mcp_started = False

    async def _ensure_mcp_started(self) -> None:
        if self._mcp_started:
            return
        try:
            await self.mcp_handler.startup()
            self._mcp_started = True
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "mcp_startup_failed — search tools unavailable",
                exc_info=True,
            )
            self._mcp_started = True  # don't retry

    async def handle_message(
        self,
        *,
        task: str,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
        analysis: ReplyDecision,
    ) -> str | None:
        async with self._lock:
            await self._ensure_mcp_started()
            self.agent.reset()
            self.action_handler.begin_turn(group_id=message.group_id)
            result = await self.agent.runtime(task=task)

            for sent_message in self.action_handler.sent_messages:
                state.record_bot_reply(
                    topic.topic_id,
                    sent_message,
                    bot_name=self.bot_name,
                    bot_id=self.bot_id,
                )
            state.record_decision(analysis)

            return result

    async def shutdown(self) -> None:
        await self.agent.shutdown()
        if self._mcp_started:
            await self.mcp_handler.shutdown()
