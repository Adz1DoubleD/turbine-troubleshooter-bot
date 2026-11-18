import asyncio
import os
from pathlib import Path

import sentry_sdk
from dotenv import find_dotenv, load_dotenv

from turbine_troubleshooter import start_troubleshooter_bot, stop_troubleshooter_bot


async def main():
    load_dotenv(find_dotenv(usecwd=True))
    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN") or os.environ.get("TROUBLESHOOTER_SENTRY_DSN")
    )
    try:
        await start_troubleshooter_bot(
            files_dir=Path(
                os.environ.get("FILES_DIR")
                or os.environ.get("TROUBLESHOOTER_FILES_DIR")
                or "media"
            ),
        )
    except ValueError as e:
        print(f"❌ {e}. Add them to .env (see .env.example).")
        return
    try:
        await asyncio.Event().wait()
    finally:
        await stop_troubleshooter_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
