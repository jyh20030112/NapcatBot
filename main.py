from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from pathlib import Path

from app.adapters.napcat_ws import NapcatWebSocketAdapter
from app.config import Settings
from app.core.json_logging import configure_json_logging, log_json
from app.handlers.group_message_handler import GroupMessageHandler
from app.services.reply_agent_service import NapcatReplyAgent

logger = logging.getLogger(__name__)


async def amain() -> None:
    configure_json_logging(level=logging.INFO)
    env_path = Path(".env")
    settings = Settings.from_env(env_path=env_path)
    adapter = NapcatWebSocketAdapter(
        host=settings.napcat_ws_host,
        port=settings.napcat_ws_port,
    )
    adapter.set_action_dry_run(settings.hide)
    agent = NapcatReplyAgent(sender=adapter)
    handler = GroupMessageHandler(
        bot_id=settings.bot_id,
        bot_name=settings.bot_name,
        agent=agent,
        hide=settings.hide,
    )
    reload_task = asyncio.create_task(
        _watch_env(
            env_path=env_path,
            settings=settings,
            adapter=adapter,
            handler=handler,
        )
    )

    try:
        await adapter.run_forever(handler)
    finally:
        reload_task.cancel()
        with suppress(asyncio.CancelledError):
            await reload_task
        await handler.shutdown()


async def _watch_env(
    *,
    env_path: Path,
    settings: Settings,
    adapter: NapcatWebSocketAdapter,
    handler: GroupMessageHandler,
    poll_seconds: float = 1.0,
) -> None:
    last_mtime = _env_mtime(env_path)
    log_json(
        logger,
        logging.DEBUG,
        "env_watcher_started",
        path=str(env_path),
        mtime=last_mtime,
    )
    while True:
        await asyncio.sleep(poll_seconds)
        current_mtime = _env_mtime(env_path)
        if current_mtime == last_mtime:
            continue
        last_mtime = current_mtime

        try:
            new_settings = Settings.from_env(env_path=env_path)
            if (
                new_settings.napcat_ws_host != settings.napcat_ws_host
                or new_settings.napcat_ws_port != settings.napcat_ws_port
            ):
                log_json(
                    logger,
                    logging.WARNING,
                    "env_ws_endpoint_changed",
                    old_host=settings.napcat_ws_host,
                    old_port=settings.napcat_ws_port,
                    new_host=new_settings.napcat_ws_host,
                    new_port=new_settings.napcat_ws_port,
                    reason="websocket listener endpoint requires process restart",
                )

            adapter.set_action_dry_run(new_settings.hide)
            new_agent = NapcatReplyAgent(sender=adapter)
            await handler.reload_runtime(
                bot_id=new_settings.bot_id,
                bot_name=new_settings.bot_name,
                agent=new_agent,
                hide=new_settings.hide,
            )
            settings = new_settings
            log_json(
                logger,
                logging.INFO,
                "env_reloaded",
                path=str(env_path),
                bot_id=settings.bot_id,
                bot_name=settings.bot_name,
                hide=settings.hide,
            )
        except Exception:
            logger.log(
                logging.ERROR,
                "env_reload_failed",
                exc_info=True,
                extra={"event": "env_reload_failed", "data": {"path": str(env_path)}},
            )


def _env_mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
