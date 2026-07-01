from __future__ import annotations

import asyncio

from simagentplg import BaseAgent, ModelConfig

from app.core.reply import ReplyDecision
from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage
from app.llms_tools.napcat_action_tools import NapcatActionToolHandler, NapcatActionSender


SYSTEM_PROMPT = """
你是一个 QQ 群里的普通群友，不是客服机器人。

你的任务是根据已经给出的 ReplyDecision 执行动作，并且只能通过工具行动。

群聊原则：
1. 不要重新做意图识别，ReplyDecision 是上游 Decision Agent 给出的结论。
2. 回复当前话题，不要只看最后一句。
3. 如果 ReplyDecision 要求不回复，调用 skip_reply。
4. 有争吵、嘲讽、拉踩、引战风险时，只轻轻降温或跳过。
5. 回复要像群友，短、自然、别端着，不要 Markdown。
6. 所有 QQ 动作必须通过 function call 完成，禁止输出普通文本当作回复。

可用动作：
- skip_reply：不回复。
- send_msg：向当前群发普通消息。
- send_at_msg：@ 某个成员并发送消息。
""".strip()


class NapcatReplyAgent:
    def __init__(
        self,
        *,
        sender: NapcatActionSender,
        config: ModelConfig | None = None,
        max_steps: int = 4,
    ) -> None:
        self.action_handler = NapcatActionToolHandler(sender)
        self.agent = BaseAgent(
            config=config or ModelConfig.from_env(),
            agent_id="napcat_group_agent",
            system_prompt=SYSTEM_PROMPT,
            handlers=[self.action_handler],
            enable_tools=True,
            max_steps=max_steps,
        )
        self._lock = asyncio.Lock()

    async def handle_message(
        self,
        *,
        task: str,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
        decision: ReplyDecision,
    ) -> str | None:
        async with self._lock:
            self.agent.reset()
            self.action_handler.begin_turn(group_id=message.group_id)
            result = await self.agent.runtime(task=task)

            for sent_message in self.action_handler.sent_messages:
                state.record_bot_reply(topic.topic_id, sent_message)
            state.record_decision(decision)

            return result

    async def shutdown(self) -> None:
        await self.agent.shutdown()
