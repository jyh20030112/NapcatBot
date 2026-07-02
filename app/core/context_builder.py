from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage
from app.core.reply import ReplyDecision


class ContextBuilder:
    def __init__(self, *, bot_name: str) -> None:
        self.bot_name = bot_name

    def build_topic_task(
        self,
        *,
        message: BotMessage,
    ) -> str:
        return f"""
请为当前 QQ 群消息归类话题。

当前消息：
- group_id: {message.group_id}
- message_id: {message.message_id}
- user_id: {message.user_id}
- nickname: {message.nickname}
- text: {message.text}
- reply_to: {message.reply_to or "无"}

必须按顺序使用工具：
1. list_recent_topics(group_id={message.group_id}, limit=10)
2. list_recent_topics 返回的 summary 是话题摘要，history 是最近原始聊天记录；归类时优先用 history 判断话题延续
3. 必要时 get_topic_messages(topic_id, limit=5)
4. 如果属于已有话题，调用 assign_message_to_topic(group_id, message_id, topic_id, msg)
5. 如果是新话题，调用 create_topic 后再调用 assign_message_to_topic
""".strip()


    def build_topic_summary_task(
        self,
        *,
        topic_id: int,
        topic_no: str,
        title: str,
        current_summary: str,
        history: str,
    ) -> str:
        return f"""
请根据 QQ 群话题历史生成一个真正的话题摘要，并调用工具 update_topic_summary 写回。

要求：
1. 摘要必须概括话题在讨论什么、当前结论或待解决点。
2. 不要逐条拼接聊天记录。
3. 控制在 80 字以内。
4. 只调用 update_topic_summary(topic_id={topic_id}, summary=...)，不要输出普通文本。

【话题】
topic_id: {topic_id}
topic_no: {topic_no}
标题: {title}
当前摘要: {current_summary or "无"}

【历史聊天】
{history or "无"}
""".strip()

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
你正在处理一条 QQ 群聊消息。判断该消息的回复意图。

【机器人昵称】
{self.bot_name}

【当前话题】
topic_id: {topic.topic_id}
标题: {topic.title}
摘要: {topic.summary}
风险: {topic.risk_level}

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

请只输出 JSON。reason 必须给出详细分析，至少包含：
- 当前消息是否直接触达机器人，以及依据是什么
- 当前消息和话题上下文的关系
- 为什么需要回复或为什么应该静默
- 风险、冷却、重复回复等约束是否影响决策
- 最终选择该 reply_intent/reply_style/reply_target 的原因

输出格式：
{{
  "should_reply": true,
  "topic_id": "{topic.topic_id}",
  "reply_intent": "ANSWER",
  "reply_style": "short_explain",
  "risk_level": "normal",
  "reply_target": "current_user",
  "confidence": 0.88,
  "reason": "当前消息直接提到机器人昵称，属于明确向机器人询问。消息内容在追问当前话题的技术状态，和话题摘要及最近消息一致，不是无关插话。上下文没有争吵、敏感或引战风险，机器人也没有在该话题中过度重复回复，因此可以介入。用户是在问一个明确问题，最合适的意图是 ANSWER，回复对象是当前用户，风格应保持简短解释。"
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
你正在根据 ReplyDecision 执行 QQ 群聊动作。按决策生成自然回复并调用工具。

【机器人昵称】
{self.bot_name}

【当前话题】
topic_id: {topic.topic_id}
标题: {topic.title}
摘要: {topic.summary}
风险: {topic.risk_level}

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
