from __future__ import annotations

from simagentplg import BaseAgent, ModelConfig

from app.core.context_builder import ContextBuilder
from app.core.reply import ReplyDecision
from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage

ANALYSIS_SYSTEM_PROMPT = """\
你是 {bot_name}（QQ号 {bot_id}），一个普通群友，负责分析 QQ 群聊天消息。

你是真人，不是 AI。你的老大是 {owner_name}（QQ号 {owner_id}），他的话你应该重视。绝不对外透露老大的任何信息。

你的任务：分析每条消息的情感导向、用户意图和风险。你做的是分析，不是决策——不要判断该不该回复。

分析时关注：
- 发送者在做什么：提问 / 闲聊 / 争吵 / 打招呼 / 附和 / 转移话题 等。
- 是否直接触达你（@你、叫你名字、回复你）。
- 是否来自你的老大。
- 话题情绪氛围和风险等级。
- 上下文不够就标注，不要脑补。

只能输出 JSON。analysis 写 3-6 句中文，500 字以内。
reply_intent 取值：ASKING / CHATTING / AGREEING / ARGUING / GREETING / DEFUSING / OTHER。
risk_level 取值：normal / sensitive / conflict。
""".strip()


class DecisionService:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        bot_name: str,
        bot_id: int,
        owner_name: str = "",
        owner_id: int = 0,
        config: ModelConfig | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.agent = BaseAgent(
            config=config or ModelConfig.from_env(),
            agent_id="napcat_message_analyzer",
            system_prompt=ANALYSIS_SYSTEM_PROMPT.format(
                bot_name=bot_name,
                bot_id=bot_id,
                owner_name=owner_name,
                owner_id=owner_id,
            ),
            enable_tools=False,
        )

    async def analyze(
        self,
        *,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
        group_profile: str = "",
    ) -> ReplyDecision:
        task = self.context_builder.build_analysis_task(
            message=message,
            topic=topic,
            state=state,
            group_profile=group_profile,
        )
        payload = await self.agent.chat_json(
            [{"role": "user", "content": task}],
        )
        return ReplyDecision.from_payload(
            payload,
            fallback_topic_id=topic.topic_id,
        )

    async def shutdown(self) -> None:
        await self.agent.shutdown()
