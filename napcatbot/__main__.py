import asyncio
import sys

from napcatbot.main import main, run_with_reload


if __name__ == "__main__":
    if "--reload" in sys.argv:
        run_with_reload()
    else:
        asyncio.run(main())
