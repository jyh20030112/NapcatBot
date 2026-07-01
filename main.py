from __future__ import annotations

import asyncio
import logging

from app.adapters.napcat_ws import NapcatWebSocketAdapter
from app.config import Settings
from app.core.json_logging import configure_json_logging
from app.handlers.group_message_handler import GroupMessageHandler
from app.services.agent_service import NapcatGroupAgent


async def amain() -> None:
    configure_json_logging(level=logging.INFO)
    settings = Settings.from_env()
    adapter = NapcatWebSocketAdapter(
        host=settings.napcat_ws_host,
        port=settings.napcat_ws_port,
    )
    agent = NapcatGroupAgent(sender=adapter)
    handler = GroupMessageHandler(
        bot_id=settings.bot_id,
        bot_name=settings.bot_name,
        agent=agent,
    )

    try:
        await adapter.run_forever(handler)
    finally:
        await handler.shutdown()
        await agent.shutdown()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
