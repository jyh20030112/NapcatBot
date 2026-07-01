from __future__ import annotations

from app.core.reply_decision import RiskLevel


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
