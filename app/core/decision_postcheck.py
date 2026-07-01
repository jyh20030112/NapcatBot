from __future__ import annotations

from app.core.reply_decision import ReplyDecision
from app.core.group_state import GroupState, TopicState
from app.core.message import BotMessage


def post_check_decision(
    decision: ReplyDecision,
    *,
    message: BotMessage,
    topic: TopicState,
    state: GroupState,
    cooldown_seconds: int = 20,
    min_confidence: float = 0.6,
    indirect_confidence: float = 0.8,
) -> ReplyDecision:
    if decision.confidence < min_confidence:
        return ReplyDecision.silence(
            topic_id=topic.topic_id,
            reason=f"confidence too low: {decision.confidence:.2f}",
            risk_level=decision.risk_level,
        )

    if topic.risk_level == "conflict" or decision.risk_level == "conflict":
        if decision.reply_intent not in {"SILENCE", "COOL_DOWN", "DEFLECT"}:
            return ReplyDecision(
                should_reply=True,
                topic_id=topic.topic_id,
                reply_intent="COOL_DOWN",
                reply_style="cool_down",
                risk_level="conflict",
                reply_target=decision.reply_target,
                confidence=decision.confidence,
                reason="conflict topic forced to cool down",
            )

    directly_addressed = (
        message.is_at_bot
        or message.reply_to_bot
        or message.mentions_bot_name
    )
    if not directly_addressed and decision.confidence < indirect_confidence:
        return ReplyDecision.silence(
            topic_id=topic.topic_id,
            reason="not directly addressed and confidence is not high enough",
            risk_level=decision.risk_level,
        )

    if (
        not directly_addressed
        and state.bot_replied_recently(seconds=cooldown_seconds)
    ):
        return ReplyDecision.silence(
            topic_id=topic.topic_id,
            reason=f"bot replied within {cooldown_seconds}s",
            risk_level=decision.risk_level,
        )

    if not directly_addressed and topic.bot_replied_count:
        return ReplyDecision.silence(
            topic_id=topic.topic_id,
            reason="bot already replied twice in this topic",
            risk_level=decision.risk_level,
        )

    if _is_low_value_message(message.text) and not directly_addressed:
        return ReplyDecision.silence(
            topic_id=topic.topic_id,
            reason="low value group message",
            risk_level=decision.risk_level,
        )

    return decision


def _is_low_value_message(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) <= 2 and stripped in {"?", "？", "啊", "嗯", "哦", "草"}:
        return True
    return False
