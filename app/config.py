from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    napcat_ws_host: str
    napcat_ws_port: int
    bot_id: int
    bot_name: str = "蛋总"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

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

        return cls(
            napcat_ws_host=ws_host,
            napcat_ws_port=ws_port,
            bot_id=bot_id,
            bot_name=bot_name,
        )
