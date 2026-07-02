from __future__ import annotations

from datetime import datetime
import json
import logging
import sys
import traceback
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
        }
        event = getattr(record, "event", None)
        data = getattr(record, "data", None)
        if event:
            payload["event"] = event
        else:
            payload["message"] = record.getMessage()
        if isinstance(data, dict):
            payload["data"] = data
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


def configure_json_logging(*, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)

    for logger_name in (
        "httpx",
        "httpcore",
        "websockets",
        "websockets.server",
        "napcat_topic_classifier",
        "napcat_topic_summarizer",
        "napcat_group_agent",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def log_json(
    logger: logging.Logger,
    level: int,
    event: str,
    **data: Any,
) -> None:
    logger.log(level, event, extra={"event": event, "data": data})
