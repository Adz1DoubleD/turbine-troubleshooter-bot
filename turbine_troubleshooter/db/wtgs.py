from .core import db_session


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
