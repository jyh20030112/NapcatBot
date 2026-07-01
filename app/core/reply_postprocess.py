import re


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
