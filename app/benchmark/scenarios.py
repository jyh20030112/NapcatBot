"""Benchmark scenario definitions.

Each scenario describes:
- A group_id and optional seed messages to pre-populate state
- A test event (raw OneBot JSON) to inject
- Fake LLM behavior configuration (what tools to dispatch, what reply to give)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BOT_ID = 123456789
BOT_NAME = "蛋总"
OWNER_NAME = "蛋烧肉粽"
OWNER_ID = 944878197


@dataclass(slots=True)
class Scenario:
    name: str
    description: str
    group_id: int
    bot_id: int = BOT_ID
    bot_name: str = BOT_NAME
    owner_name: str = OWNER_NAME
    owner_id: int = OWNER_ID
    # Messages to feed through handler before the test (populates state + topics)
    seed_events: list[dict[str, Any]] = field(default_factory=list)
    # The event whose processing latency is measured
    test_event: dict[str, Any] = field(default_factory=dict)
    # Fake LLM configuration
    topic_action: str = "create_new"  # "create_new" | "assign_existing"
    decision_payload: dict[str, Any] = field(default_factory=dict)
    reply_action: str = "send_msg"  # "send_msg" | "send_at_msg" | "skip_reply"
    reply_text: str = "benchmark reply"
    # Whether a group profile is expected (False = empty string)
    expects_profile: bool = False


# ---------------------------------------------------------------------------
# Shared message builders
# ---------------------------------------------------------------------------


def _plain_msg(
    group_id: int,
    user_id: int,
    message_id: str,
    nickname: str,
    text: str,
) -> dict[str, Any]:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": user_id,
        "message_id": message_id,
        "sender": {"nickname": nickname},
        "message": text,
    }


def _at_msg(
    group_id: int,
    user_id: int,
    message_id: str,
    nickname: str,
    text: str,
) -> dict[str, Any]:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": user_id,
        "message_id": message_id,
        "sender": {"nickname": nickname},
        "message": [
            {"type": "at", "data": {"qq": str(BOT_ID)}},
            {"type": "text", "data": {"text": f" {text}"}},
        ],
    }


def _reply_msg(
    group_id: int,
    user_id: int,
    message_id: str,
    nickname: str,
    text: str,
    reply_to: str,
) -> dict[str, Any]:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": user_id,
        "message_id": message_id,
        "sender": {"nickname": nickname},
        "message": [
            {"type": "reply", "data": {"id": reply_to}},
            {"type": "text", "data": {"text": f" {text}"}},
        ],
    }


# ---------------------------------------------------------------------------
# Scenario 1: new_topic
# No existing topics. First message creates a new topic via LLM.
# ---------------------------------------------------------------------------

NEW_TOPIC = Scenario(
    name="new_topic",
    description="No existing topics → LLM creates a new topic",
    group_id=1000,
    seed_events=[],
    test_event=_at_msg(
        group_id=1000,
        user_id=2001,
        message_id="msg_new_001",
        nickname="小明",
        text="这个项目部署到哪台机器上了？",
    ),
    topic_action="create_new",
    decision_payload={
        "topic_id": "",
        "reply_intent": "ASKING",
        "risk_level": "normal",
        "analysis": "消息直接@了蛋总，询问项目部署位置，属于明确提问。情绪友好无风险。",
    },
    reply_action="send_at_msg",
    reply_text="部署在 192.168.1.100 上，你要上去看看吗？",
)

# ---------------------------------------------------------------------------
# Scenario 2: existing_topic
# One existing topic. The LLM classifies a new message into it.
# ---------------------------------------------------------------------------

_EXISTING_SEED = _plain_msg(
    group_id=1000,
    user_id=2002,
    message_id="msg_prior_001",
    nickname="小红",
    text="部署脚本报错了，有人能看一下吗？",
)

EXISTING_TOPIC = Scenario(
    name="existing_topic",
    description="Pre-existing topic → LLM classifies message into it",
    group_id=1000,
    seed_events=[_EXISTING_SEED],
    test_event=_plain_msg(
        group_id=1000,
        user_id=2003,
        message_id="msg_existing_001",
        nickname="小华",
        text="报错的是不是权限问题？我上次也遇到过",
    ),
    topic_action="assign_existing",
    decision_payload={
        "topic_id": "",
        "reply_intent": "CHATTING",
        "risk_level": "normal",
        "analysis": "消息延续了部署报错的话题，小华推测是权限问题。未直接@机器人，属于正常讨论。",
    },
    reply_action="send_msg",
    reply_text="有可能，检查一下 /data 目录的写权限",
)

# ---------------------------------------------------------------------------
# Scenario 3: reply_to_inherit
# Reply to a known message → FAST PATH (no topic LLM call).
# ---------------------------------------------------------------------------

_REPLY_SEED = _plain_msg(
    group_id=1000,
    user_id=2004,
    message_id="msg_prior_002",
    nickname="小李",
    text="谁知道 CI 配置文件在哪改？",
)

REPLY_TO_INHERIT = Scenario(
    name="reply_to_inherit",
    description="Reply to known message → fast path inherits topic (no topic LLM)",
    group_id=1000,
    seed_events=[_REPLY_SEED],
    test_event=_reply_msg(
        group_id=1000,
        user_id=2005,
        message_id="msg_reply_001",
        nickname="小张",
        text="我也想问，有没有文档链接？",
        reply_to="msg_prior_002",
    ),
    topic_action="assign_existing",  # fast path: state.message_topic_map hit
    decision_payload={
        "topic_id": "",
        "reply_intent": "ASKING",
        "risk_level": "normal",
        "analysis": "小张回复了小李的CI配置问题，同样想获取文档链接。问题延续，情绪正常。",
    },
    reply_action="send_msg",
    reply_text="文档在 wiki 首页置顶了，搜 CI 配置就能找到",
)

# ---------------------------------------------------------------------------
# Scenario 4: first_message
# Empty group — no topics, no profile. Same as new_topic but validates
# the empty-group_profile code path.
# ---------------------------------------------------------------------------

FIRST_MESSAGE = Scenario(
    name="first_message",
    description="First ever message in a group — no cached profile, no topics",
    group_id=2000,
    seed_events=[],
    test_event=_at_msg(
        group_id=2000,
        user_id=2006,
        message_id="msg_first_001",
        nickname="新人",
        text="大家好，刚进群，请问这个群主要聊什么？",
    ),
    topic_action="create_new",
    decision_payload={
        "topic_id": "",
        "reply_intent": "GREETING",
        "risk_level": "normal",
        "analysis": "新成员进群打招呼，询问群聊主题。情绪友好，属于GREETING。",
    },
    reply_action="send_at_msg",
    reply_text="欢迎！这个群主要聊技术部署和运维，有啥问题随时问",
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_SCENARIOS: dict[str, Scenario] = {
    "new_topic": NEW_TOPIC,
    "existing_topic": EXISTING_TOPIC,
    "reply_to_inherit": REPLY_TO_INHERIT,
    "first_message": FIRST_MESSAGE,
}
