from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal, get_args


ReplyIntent = Literal[
    "ASKING",
    "CHATTING",
    "AGREEING",
    "ARGUING",
    "GREETING",
    "DEFUSING",
    "OTHER",
]
RiskLevel = Literal["normal", "sensitive", "conflict"]


@dataclass(slots=True)
class ReplyDecision:
    should_reply: bool = True
    topic_id: str = ""
    reply_intent: ReplyIntent = "OTHER"
    risk_level: RiskLevel = "normal"
    confidence: float = 1.0
    reason: str = ""

    @classmethod
    def silence(
        cls,
        *,
        topic_id: str,
        reason: str,
        risk_level: RiskLevel = "normal",
    ) -> "ReplyDecision":
        return cls(
            should_reply=False,
            topic_id=topic_id,
            reply_intent="OTHER",
            risk_level=risk_level,
            confidence=1.0,
            reason=reason,
        )

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_topic_id: str,
    ) -> "ReplyDecision":
        return cls(
            topic_id=str(payload.get("topic_id") or fallback_topic_id),
            reply_intent=_literal_value(
                payload.get("reply_intent"),
                ReplyIntent,
                default="OTHER",
            ),
            risk_level=_literal_value(
                payload.get("risk_level"),
                RiskLevel,
                default="normal",
            ),
            confidence=_float_between(payload.get("confidence"), 0.0, 1.0),
            reason=str(payload.get("analysis") or payload.get("reason") or "no reason")[:1200],
        )


CONFLICT_WORDS = (
    "急了",
    "破防",
    "你懂不懂",
    "你不行",
    "傻",
    "废物",
    "滚",
    "骂",
    "sb",
    "nt",
)
SENSITIVE_WORDS = (
    "地域黑",
    "女拳",
    "饭圈",
    "穷鬼",
    "学历低",
    "政治",
    "拉踩",
    "开盒",
    "人肉",
    "举报",
)


def detect_risk(text: str) -> RiskLevel:
    lowered = text.lower()
    if any(word in lowered for word in CONFLICT_WORDS):
        return "conflict"
    if any(word in lowered for word in SENSITIVE_WORDS):
        return "sensitive"
    return "normal"


MAX_REPLY_LENGTH = 180


def clean_reply(text: str, *, max_length: int = MAX_REPLY_LENGTH) -> str:
    text = text.strip()
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"[*_`>#~-]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _literal_value(value: Any, literal_type: Any, *, default: Any) -> Any:
    allowed = set(get_args(literal_type))
    return value if value in allowed else default


def _float_between(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))
