from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, get_args


ReplyIntent = Literal[
    "SILENCE",
    "ANSWER",
    "AGREE",
    "ASK_BACK",
    "JOKE_LIGHT",
    "COOL_DOWN",
    "DEFLECT",
]
ReplyStyle = Literal[
    "short_reply",
    "short_explain",
    "ask_one_question",
    "light_joke",
    "cool_down",
    "end_topic",
]
RiskLevel = Literal["normal", "sensitive", "conflict"]
ReplyTarget = Literal["current_user", "topic", "group"]


@dataclass(slots=True)
class ReplyDecision:
    should_reply: bool
    topic_id: str
    reply_intent: ReplyIntent
    reply_style: ReplyStyle
    risk_level: RiskLevel
    reply_target: ReplyTarget
    confidence: float
    reason: str

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
            reply_intent="SILENCE",
            reply_style="short_reply",
            risk_level=risk_level,
            reply_target="topic",
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
        intent = _literal_value(
            payload.get("reply_intent"),
            ReplyIntent,
            default="SILENCE",
        )
        should_reply = bool(payload.get("should_reply", False))
        if intent == "SILENCE":
            should_reply = False

        confidence = _float_between(payload.get("confidence"), 0.0, 1.0)
        return cls(
            should_reply=should_reply,
            topic_id=str(payload.get("topic_id") or fallback_topic_id),
            reply_intent=intent,
            reply_style=_literal_value(
                payload.get("reply_style"),
                ReplyStyle,
                default="short_reply",
            ),
            risk_level=_literal_value(
                payload.get("risk_level"),
                RiskLevel,
                default="normal",
            ),
            reply_target=_literal_value(
                payload.get("reply_target"),
                ReplyTarget,
                default="topic",
            ),
            confidence=confidence,
            reason=str(payload.get("reason") or "no reason")[:240],
        )


def _literal_value(value: Any, literal_type: Any, *, default: Any) -> Any:
    allowed = set(get_args(literal_type))
    return value if value in allowed else default


def _float_between(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))
