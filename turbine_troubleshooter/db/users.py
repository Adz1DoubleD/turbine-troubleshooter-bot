"""Users, admins and access requests."""

from typing import Any

from .core import db_session

USER_COLUMNS = (
    "SELECT user_id, username, is_admin, last_login, notifications_enabled, "
    "is_approved FROM users"
)


async def admin_add(user_id: int, username: str | None = None) -> None:
    query = """
    INSERT INTO users (user_id, username, is_admin)
    VALUES (%(user_id)s, %(username)s, 1) AS new
    ON DUPLICATE KEY UPDATE
        username = new.username,
        is_admin = 1
    """
    async with db_session() as cur:
        await cur.execute(query, {"user_id": user_id, "username": username})


async def admin_remove(user_id: int) -> bool:
    query = "UPDATE users SET is_admin = 0 WHERE user_id = %s"
    async with db_session() as cur:
        await cur.execute(query, (user_id,))
        return cur.rowcount > 0


async def user_add(user_id: int, username: str | None = None) -> bool:
    async with db_session() as cur:
        await cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        exists = await cur.fetchone()

        if not exists:
            await cur.execute(
                "INSERT INTO users (user_id, username, is_admin, last_login) "
                "VALUES (%s, %s, 0, NOW())",
                (user_id, username),
            )
            return True

        await cur.execute(
            "UPDATE users SET username = %s, last_login = NOW() WHERE user_id = %s",
            (username, user_id),
        )
        return False


async def user_approve(user_id: int) -> bool:
    async with db_session() as cur:
        await cur.execute(
            "UPDATE users SET is_approved = 1 WHERE user_id = %s", (user_id,)
        )
        return cur.rowcount > 0


async def user_revoke(user_id: int) -> bool:
    async with db_session() as cur:
        await cur.execute(
            "UPDATE users SET is_approved = 0 WHERE user_id = %s", (user_id,)
        )
        return cur.rowcount > 0


async def request_add(user_id: int, kind: str, name: str | None = None) -> None:
    async with db_session() as cur:
        await cur.execute(
            "INSERT INTO requests (user_id, kind, name) VALUES (%s, %s, %s) AS new "
            "ON DUPLICATE KEY UPDATE kind = new.kind, name = new.name, "
            "requested_at = NOW()",
            (user_id, kind, name),
        )


async def request_remove(user_id: int) -> bool:
    async with db_session() as cur:
        await cur.execute("DELETE FROM requests WHERE user_id = %s", (user_id,))
        return cur.rowcount > 0


async def users_get() -> list[dict[str, Any]]:
    async with db_session() as cur:
        await cur.execute(USER_COLUMNS)
        return [_user_from_row(r) for r in await cur.fetchall()]


async def user_get(user_id: int) -> dict[str, Any] | None:
    async with db_session() as cur:
        await cur.execute(f"{USER_COLUMNS} WHERE user_id = %s", (user_id,))
        row = await cur.fetchone()
        return _user_from_row(row) if row else None


async def user_notifications_toggle(user_id: int) -> int | None:
    async with db_session() as cur:
        await cur.execute(
            "UPDATE users SET notifications_enabled = 1 - notifications_enabled WHERE user_id = %s",
            (user_id,),
        )
        await cur.execute(
            "SELECT notifications_enabled FROM users WHERE user_id = %s", (user_id,)
        )
        row = await cur.fetchone()
        return int(row["notifications_enabled"]) if row else None


async def user_notifications_get(user_id: int) -> int:
    async with db_session() as cur:
        await cur.execute(
            "SELECT notifications_enabled FROM users WHERE user_id = %s", (user_id,)
        )
        row = await cur.fetchone()
        return int(row["notifications_enabled"]) if row else 1


def _user_from_row(record: Any) -> dict[str, Any]:
    return {
        "user_id": int(record["user_id"]),
        "username": record.get("username"),
        "is_admin": int(record["is_admin"]),
        "last_login": record.get("last_login"),
        "notifications_enabled": int(record.get("notifications_enabled", 1)),
        "is_approved": int(record.get("is_approved") or 0),
    }
