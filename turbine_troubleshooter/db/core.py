"""The database connection pool and shared queries."""

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import aiomysql
import sentry_sdk

from ..settings import SETTINGS

DB_POOL_SIZE = 3
DB_CONNECT_TIMEOUT = 10
DB_POOL_RECYCLE = 280
_pool = None
_pool_lock = asyncio.Lock()


async def get_db_pool():
    global _pool
    async with _pool_lock:
        if _pool is None:
            url = SETTINGS.db_url
            if not url:
                raise RuntimeError(f"{SETTINGS.env_prefix}DB_URL is not set")
            db_url = urlparse(url)
            _pool = await aiomysql.create_pool(
                host=db_url.hostname,
                user=db_url.username,
                password=db_url.password,
                port=db_url.port,
                db=db_url.path[1:],
                autocommit=True,
                minsize=1,
                maxsize=DB_POOL_SIZE,
                connect_timeout=DB_CONNECT_TIMEOUT,
                pool_recycle=DB_POOL_RECYCLE,
            )
    return _pool


@asynccontextmanager
async def db_session():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                yield cur
            except Exception as e:
                sentry_sdk.capture_exception(e)
                raise


async def close_db():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


async def get_neighbours(curr_id: int, table: str, order_by: str = "id"):
    async with db_session() as cur:
        await cur.execute(
            f"""
            SELECT
                (SELECT id FROM `{table}` WHERE `{order_by}` < c.`{order_by}`
                 ORDER BY `{order_by}` DESC LIMIT 1) AS prev_id,
                (SELECT id FROM `{table}` WHERE `{order_by}` > c.`{order_by}`
                 ORDER BY `{order_by}` ASC LIMIT 1) AS next_id
            FROM `{table}` c
            WHERE c.id = %s
        """,
            (curr_id,),
        )
        row = await cur.fetchone()
        return (row["prev_id"], row["next_id"]) if row else (None, None)


async def delete_entry(table, column, value):
    async with db_session() as cur:
        await cur.execute(f"DELETE FROM `{table}` WHERE `{column}` = %s", (value,))
        return cur.rowcount > 0
