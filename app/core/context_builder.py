from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage
from app.core.decision import ReplyDecision


class ContextBuilder:
    def __init__(self, *, bot_name: str) -> None:
        self.bot_name = bot_name

    def build_decision_task(
        self,
        *,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
    ) -> str:
        recent_messages = "\n".join(
            f"{item.nickname}: {item.text}"
            for item in state.recent_messages[-12:]
            if item.text
        )
        topic_messages = "\n".join(
            f"{item.nickname}: {item.text}"
            for item in topic.last_messages[-8:]
            if item.text
        )
        bot_replies = "\n".join(
            f"{index}. {reply}"
            for index, reply in enumerate(state.bot_recent_replies[-5:], start=1)
        ) or "无"

        return f"""
你正在处理一条 QQ 群聊消息。请判断机器人这轮该不该回复，以及回复意图。

【机器人昵称】
{self.bot_name}

【当前话题】
topic_id: {topic.topic_id}
标题: {topic.title}
摘要: {topic.summary}
风险: {topic.risk_level}
机器人在该话题已回复次数: {topic.bot_replied_count}

【该话题最近消息】
{topic_messages or "无"}

【当前群最近消息】
{recent_messages or "无"}

【机器人最近回复】
{bot_replies}

【当前消息】
发送者: {message.nickname}
发送者QQ: {message.user_id}
内容: {message.text}
是否@机器人: {message.is_at_bot}
是否提到机器人昵称: {message.mentions_bot_name}
是否回复某条消息: {bool(message.reply_to)}

请只输出 JSON：
{{
  "should_reply": true,
  "topic_id": "{topic.topic_id}",
  "reply_intent": "ANSWER",
  "reply_style": "short_explain",
  "risk_level": "normal",
  "reply_target": "current_user",
  "confidence": 0.88,
  "reason": "用户在追问当前技术方案"
}}
""".strip()

    def build_action_task(
        self,
        *,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
        decision: ReplyDecision,
    ) -> str:
        recent_messages = "\n".join(
            f"{item.nickname}: {item.text}"
            for item in state.recent_messages[-12:]
            if item.text
        )
        topic_messages = "\n".join(
            f"{item.nickname}: {item.text}"
            for item in topic.last_messages[-8:]
            if item.text
        )
        bot_replies = "\n".join(
            f"{index}. {reply}"
            for index, reply in enumerate(state.bot_recent_replies[-5:], start=1)
        ) or "无"

        return f"""
你正在根据 ReplyDecision 执行 QQ 群聊动作。不要重新做意图识别，只按决策生成自然回复并调用工具。

【机器人昵称】
{self.bot_name}

【当前话题】
topic_id: {topic.topic_id}
标题: {topic.title}
摘要: {topic.summary}
风险: {topic.risk_level}
机器人在该话题已回复次数: {topic.bot_replied_count}

【ReplyDecision】
should_reply: {decision.should_reply}
reply_intent: {decision.reply_intent}
reply_style: {decision.reply_style}
risk_level: {decision.risk_level}
reply_target: {decision.reply_target}
confidence: {decision.confidence}
reason: {decision.reason}

【该话题最近消息】
{topic_messages or "无"}

【当前群最近消息】
{recent_messages or "无"}

【机器人最近回复】
{bot_replies}

【当前消息】
发送者: {message.nickname}
发送者QQ: {message.user_id}
内容: {message.text}
是否@机器人: {message.is_at_bot}
是否提到机器人昵称: {message.mentions_bot_name}
是否回复某条消息: {bool(message.reply_to)}

行动要求：
1. 如果 should_reply 为 false，调用 skip_reply。
2. 如果 reply_target 是 current_user，优先调用 send_at_msg，user_id 使用当前发送者QQ。
3. 其他自然群聊回复调用 send_msg。
4. 回复要短、自然、像 QQ 群友，不要 Markdown。
5. 不要输出普通文本；所有 QQ 动作必须通过工具调用完成。
""".strip()
