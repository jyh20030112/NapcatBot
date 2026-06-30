import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from napcatbot.main import main, run_with_reload


if __name__ == "__main__":
    if "--reload" in sys.argv:
        run_with_reload()
    else:
        asyncio.run(main())
