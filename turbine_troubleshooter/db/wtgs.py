import json

from .core import db_session

WTGS_MIGRATED = "wtgs_migrated"


async def wtgs_migrate(wtgs_json):
    async with db_session() as cur:
        await cur.execute("SHOW TABLES LIKE 'wtgs'")
        if not await cur.fetchone():
            await cur.execute("""
                CREATE TABLE wtgs (
                    wtg VARCHAR(32) PRIMARY KEY,
                    serial VARCHAR(64) NULL,
                    ip VARCHAR(64) NULL,
                    sort_order INT NOT NULL DEFAULT 0
                ) DEFAULT CHARSET=utf8mb4
            """)

        await cur.execute(
            "SELECT value FROM settings WHERE name = %s", (WTGS_MIGRATED,)
        )
        if await cur.fetchone():
            return 0

        turbines = [
            (
                wtg,
                None if info.get("serial") is None else str(info["serial"]),
                info.get("ip"),
                order,
            )
            for order, (wtg, info) in enumerate(
                (json.loads(wtgs_json) if wtgs_json else {}).items(), 1
            )
            if isinstance(info, dict)
        ]

        await cur.execute("START TRANSACTION")
        try:
            for turbine in turbines:
                await cur.execute(
                    "INSERT INTO wtgs (wtg, serial, ip, sort_order) "
                    "VALUES (%s, %s, %s, %s)",
                    turbine,
                )
            await cur.execute(
                "INSERT INTO settings (name, value) VALUES (%s, 1)", (WTGS_MIGRATED,)
            )
            await cur.execute("COMMIT")
        except Exception:
            await cur.execute("ROLLBACK")
            raise

    return len(turbines)


async def wtgs_replace(turbines):
    async with db_session() as cur:
        await cur.execute("START TRANSACTION")
        try:
            await cur.execute("DELETE FROM wtgs")
            for order, t in enumerate(turbines, 1):
                await cur.execute(
                    "INSERT INTO wtgs (wtg, serial, ip, sort_order) "
                    "VALUES (%s, %s, %s, %s)",
                    (t["wtg"], t["serial"], t["ip"], order),
                )
            await cur.execute("COMMIT")
        except Exception:
            await cur.execute("ROLLBACK")
            raise
