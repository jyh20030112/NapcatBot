from datetime import datetime, timezone, timedelta

from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage
from app.core.reply import ReplyDecision

_CN_TZ = timezone(timedelta(hours=8))


class ContextBuilder:
    def __init__(self, *, bot_name: str) -> None:
        self.bot_name = bot_name

    def build_topic_task(
        self,
        *,
        message: BotMessage,
        group_profile: str = "",
    ) -> str:
        profile_block = f"\n【群聊画像】\n{group_profile}\n" if group_profile else ""
        return f"""
请为这条 QQ 群消息归类话题。

当前时间: {datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M")}
{profile_block}
当前消息：
- group_id: {message.group_id}
- message_id: {message.message_id}
- user_id: {message.user_id}
- nickname: {message.nickname}
- text: {message.text}
- reply_to: {message.reply_to or "无"}

操作步骤：
1. list_recent_topics(group_id={message.group_id}, limit=10)
2. 如果需要更多信息，get_recent_group_messages(group_id={message.group_id}, count=20)
3. 归入已有话题 → assign_message_to_topic，或 新话题 → create_topic + assign_message_to_topic
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
根据以下话题的历史聊天生成摘要，调用 update_topic_summary(topic_id={topic_id}, summary=...) 写回。

当前时间: {datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M")}

【话题信息】
topic_id: {topic_id}
topic_no: {topic_no}
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
        group_profile: str = "",
    ) -> str:
        profile_block = f"\n【群聊画像】\n{group_profile}\n" if group_profile else ""
        return f"""
分析这条消息。只输出 JSON。

当前时间: {datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M")}
{profile_block}
【你的昵称】{self.bot_name}

【当前话题】
topic_id: {topic.topic_id} / 标题: {topic.title} / 摘要: {topic.summary} / 风险: {topic.risk_level}

【群聊最近消息】* 表示属于当前话题
{_build_message_list(topic, state, count=24)}

【当前消息】
{message.nickname}({message.user_id}): {message.text}
@你: {message.is_at_bot} / 提到你: {message.mentions_bot_name} / 回复消息: {bool(message.reply_to)}

输出格式：
{{
  "topic_id": "{topic.topic_id}",
  "reply_intent": "ASKING",
  "risk_level": "normal",
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
        group_profile: str = "",
    ) -> str:
        profile_block = f"\n【群聊画像】\n{group_profile}\n" if group_profile else ""
        return f"""
你是一个 QQ 群里的普通群友 {self.bot_name}，说话随意自然。

当前时间: {datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M")}
{profile_block}
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
{_build_message_list(topic, state, count=24)}

【当前消息】
发送者: {message.nickname}
发送者QQ: {message.user_id}
内容: {message.text}
是否@你: {message.is_at_bot}
是否提到你: {message.mentions_bot_name}
是否回复某条消息: {bool(message.reply_to)}

行动要求：
1. 自己判断该不该回，遵循群聊原则。
2. @你的人优先用 send_at_msg，普通插话用 send_msg。
3. 不要输出普通文本；所有动作必须通过工具调用完成。
""".strip()


def _build_message_list(
    topic: TopicState, state: GroupState, *, count: int = 12
) -> str:
    lines: list[str] = []
    for item in state.recent_messages[-count:]:
        if not item.text:
            continue
        in_topic = any(item is m for m in topic.last_messages)
        marker = "*" if in_topic else " "
        lines.append(f"{marker} {item.nickname}({item.user_id}): {item.text}")
    return "\n".join(lines) if lines else "无"
