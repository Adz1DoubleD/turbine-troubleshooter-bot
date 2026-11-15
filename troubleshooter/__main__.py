import asyncio
import os
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv

from troubleshooter import (
    example_content,
    start_troubleshooter_bot,
    stop_troubleshooter_bot,
)


async def main():
    load_dotenv()
    sentry_sdk.init(dsn=os.environ.get("TROUBLESHOOTER_SENTRY_DSN"))
    await start_troubleshooter_bot(
        content=example_content,
        files_dir=Path(os.environ.get("TROUBLESHOOTER_FILES_DIR", "media")),
    )
    try:
        await asyncio.Event().wait()
    finally:
        await stop_troubleshooter_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
