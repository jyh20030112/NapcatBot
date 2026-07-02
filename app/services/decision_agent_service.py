from __future__ import annotations

from simagentplg import BaseAgent, ModelConfig

from app.core.context_builder import ContextBuilder
from app.core.reply import ReplyDecision
from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage


DECISION_SYSTEM_PROMPT = """
你是 QQ 群聊天机器人的回复决策器。

你的任务不是生成聊天回复，而是判断机器人这次该不该回，以及如果要回，应该用什么方式回。

重要规则：
1. 这是 QQ 群，不是私聊。
2. 机器人不需要每条消息都回复。
3. 如果没人 @ 机器人、没人叫机器人昵称、没人回复机器人，默认倾向不回复。
4. 如果两个人正在互相聊天，机器人不要硬插话。
5. 如果机器人刚刚已经连续回复，应该降低回复概率。
6. 如果当前话题有争吵、嘲讽、拉踩、引战风险，优先选择 SILENCE、COOL_DOWN 或 DEFLECT。
7. 如果消息是明确问机器人、@ 机器人、叫机器人昵称，通常可以回复。
8. 如果上下文不够，不要脑补，选择 ASK_BACK 或 SILENCE。
9. 只能输出 JSON，不要输出解释文本。
10. reason 必须是详细分析，不是短理由；至少覆盖：直接触达信号、话题上下文、是否需要机器人介入、风险/冷却判断、最终动作原因。
11. reason 写成 3-6 句中文，控制在 500 字以内。

reply_intent 只能是：SILENCE、ANSWER、AGREE、ASK_BACK、JOKE_LIGHT、COOL_DOWN、DEFLECT。
reply_style 只能是：short_reply、short_explain、ask_one_question、light_joke、cool_down、end_topic。
risk_level 只能是：normal、sensitive、conflict。
reply_target 只能是：current_user、topic、group。
""".strip()


class DecisionService:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        config: ModelConfig | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.agent = BaseAgent(
            config=config or ModelConfig.from_env(),
            agent_id="napcat_reply_decision",
            system_prompt=DECISION_SYSTEM_PROMPT,
            enable_tools=False,
        )

    async def decide(
        self,
        *,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
    ) -> ReplyDecision:
        task = self.context_builder.build_decision_task(
            message=message,
            topic=topic,
            state=state,
        )
        payload = await self.agent.chat_json(
            [
                {"role": "system", "content": DECISION_SYSTEM_PROMPT},
                {"role": "user", "content": task},
            ],
        )
        return ReplyDecision.from_payload(
            payload,
            fallback_topic_id=topic.topic_id,
        )

    async def shutdown(self) -> None:
        await self.agent.shutdown()
