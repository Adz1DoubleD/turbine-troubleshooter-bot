from ..settings import SETTINGS
from .core import db_session


async def setting_toggle(name):
    async with db_session() as cur:
        await cur.execute(
            "INSERT INTO settings (name, value) VALUES (%s, 0) "
            "ON DUPLICATE KEY UPDATE value = 1 - value",
            (name,),
        )
        await cur.execute("SELECT value FROM settings WHERE name = %s", (name,))
        row = await cur.fetchone()
    SETTINGS.notify_settings[name] = int(row["value"]) if row else 1
    return SETTINGS.notify_settings[name]


async def setting_mark(name):
    async with db_session() as cur:
        await cur.execute(
            "INSERT IGNORE INTO settings (name, value) VALUES (%s, 1)", (name,)
        )
        added = cur.rowcount > 0
    SETTINGS.notify_settings[name] = 1
    return added
