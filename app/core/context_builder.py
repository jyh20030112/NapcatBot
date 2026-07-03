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
2. list_recent_topics 返回的 summary 是 LLM 生成的语义摘要，history 是拼接的原始聊天记录；归类时优先用 history 判断话题延续
3. 如果 summary 和 history 都不够判断，可以调 get_recent_group_messages(group_id={message.group_id}, count=20) 从 QQ 实时拉取最近的群聊消息
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
topi c_no: {topic_no}
标题: {title}
当前摘要: {current_summary or "无"}

【历史聊天】
{history or "无"}
""".strip()

    def build_analysis_task(
        self,
        *,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
    ) -> str:
        return f"""
分析这条 QQ 群聊消息的情感导向和用户意图。不要决定机器人是否回复，只做分析。

【机器人昵称】
{self.bot_name}

【当前话题】
topic_id: {topic.topic_id}
标题: {topic.title}
摘要: {topic.summary}
风险: {topic.risk_level}

【群聊最近消息】（按时间顺序，* 表示属于当前话题，包含你的回复）
{_build_message_list(topic, state)}

【当前消息】
发送者: {message.nickname}
发送者QQ: {message.user_id}
内容: {message.text}
是否@机器人: {message.is_at_bot}
是否提到机器人昵称: {message.mentions_bot_name}
是否回复某条消息: {bool(message.reply_to)}

请只输出 JSON。analysis 必须给出详细分析，至少包含：
- 当前消息是否直接触达机器人，依据是什么
- 发送者的情绪和意图（提问/闲聊/争吵/附和/打招呼等）
- 当前消息和话题上下文的关系
- 风险判断（normal / sensitive / conflict）

输出格式：
{{
  "topic_id": "{topic.topic_id}",
  "reply_intent": "ASKING",
  "risk_level": "normal",
  "confidence": 0.9,
  "analysis": "消息直接@了{self.bot_name}，发送者在询问是否在线。情绪友好，属于闲聊打招呼。话题延续了之前的相关讨论。风险正常。"
}}
""".strip()

    def build_action_task(
        self,
        *,
        message: BotMessage,
        topic: TopicState,
        state: GroupState,
        analysis: ReplyDecision,
    ) -> str:
        return f"""
你是一个 QQ 群里的普通群友 {self.bot_name}，不是客服机器人。

你需要根据上下文和分析结果，自己判断该不该回复，如果要回该怎么回。

【消息分析】
用户意图: {analysis.reply_intent}
风险等级: {analysis.risk_level}
分析: {analysis.reason}

【当前话题】
topic_id: {topic.topic_id}
标题: {topic.title}
摘要: {topic.summary}

【群聊最近消息】（按时间顺序，* 表示属于当前话题，包含你的回复）
{_build_message_list(topic, state)}

【当前消息】
发送者: {message.nickname}
发送者QQ: {message.user_id}
内容: {message.text}
是否@你: {message.is_at_bot}
是否提到你: {message.mentions_bot_name}
是否回复某条消息: {bool(message.reply_to)}

行动要求：
1. 自己判断该不该回：没人叫你、话题跟你无关、刚回过 → 调 skip_reply。
2. 被点名、话题跟你有关系、或者自然能接话 → 决定回复。
3. 回复要短、自然、像 QQ 群友，不要 Markdown。
4. @你的人优先用 send_at_msg，普通插话用 send_msg。
5. 有争吵风险时轻轻降温或跳过。
6. 不要输出普通文本；所有动作必须通过工具调用完成。
""".strip()


def _build_message_list(topic: TopicState, state: GroupState) -> str:
    topic_ids = {m.message_id for m in topic.last_messages if m.message_id}
    lines: list[str] = []
    for item in state.recent_messages[-12:]:
        if not item.text:
            continue
        marker = "*" if item.message_id in topic_ids else " "
        lines.append(f"{marker} {item.nickname}({item.user_id}): {item.text}")
    return "\n".join(lines) if lines else "无"
