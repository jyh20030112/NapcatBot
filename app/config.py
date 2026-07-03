from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    napcat_ws_host: str
    napcat_ws_port: int
    bot_id: int
    bot_name: str = "蛋总"
    hide: bool = False
    owner_name: str = ""
    owner_id: int = 0

    @classmethod
    def from_env(cls, *, env_path: str | Path = ".env") -> "Settings":
        load_dotenv(dotenv_path=env_path, override=True)

        ws_host = (
            os.getenv("NAPCAT_WS_HOST")
            or os.getenv("WS_HOST")
            or "0.0.0.0"
        ).strip()
        ws_port_raw = (
            os.getenv("NAPCAT_WS_PORT")
            or os.getenv("WS_PORT")
            or "8082"
        ).strip()
        bot_id_raw = os.getenv("BOT_ID", "").strip()
        bot_name = os.getenv("BOT_NAME", "蛋总").strip() or "蛋总"
        hide = _env_bool(os.getenv("HIDE"), default=False)
        owner_name = os.getenv("OWNER_NAME", "").strip()
        owner_id_raw = os.getenv("OWNER_ID", "0").strip()

        try:
            ws_port = int(ws_port_raw)
        except ValueError as exc:
            raise ValueError("NAPCAT_WS_PORT must be an integer") from exc
        if not bot_id_raw:
            raise ValueError("BOT_ID must be defined")
        try:
            bot_id = int(bot_id_raw)
        except ValueError as exc:
            raise ValueError("BOT_ID must be an integer") from exc
        try:
            owner_id = int(owner_id_raw)
        except ValueError:
            owner_id = 0

        return cls(
            napcat_ws_host=ws_host,
            napcat_ws_port=ws_port,
            bot_id=bot_id,
            bot_name=bot_name,
            hide=hide,
            owner_name=owner_name,
            owner_id=owner_id,
        )



def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
