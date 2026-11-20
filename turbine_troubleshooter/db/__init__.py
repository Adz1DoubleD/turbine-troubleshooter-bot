"""The troubleshooter's database: codes, parts, menus, users and settings."""

from .codes import (
    fault_code_add,
)
from .core import (
    close_db,
    db_session,
    delete_entry,
    get_db_pool,
    get_neighbours,
)
from .deletes import (
    delete_request_add,
    delete_request_remove,
)
from .export import (
    EXPORT_TABLES,
    db_export,
    db_tables,
)
from .io_boards import (
    io_boards_replace,
)
from .menu import (
    attachment_add,
    attachment_status,
    attachments_remove,
    menu_node_add,
    menu_node_delete,
    menu_node_update,
)
from .parts import (
    part_add,
    part_update,
)
from .schema import (
    init_troubleshooter_db,
)
from .settings import (
    setting_mark,
    setting_toggle,
)
from .users import (
    admin_add,
    admin_remove,
    request_add,
    request_remove,
    user_add,
    user_approve,
    user_get,
    user_notifications_get,
    user_notifications_toggle,
    user_revoke,
    users_get,
)
from .wtgs import (
    wtgs_replace,
)

__all__ = [
    "fault_code_add",
    "close_db",
    "db_session",
    "delete_entry",
    "get_db_pool",
    "get_neighbours",
    "delete_request_add",
    "delete_request_remove",
    "EXPORT_TABLES",
    "db_export",
    "db_tables",
    "io_boards_replace",
    "attachment_add",
    "attachment_status",
    "attachments_remove",
    "menu_node_add",
    "menu_node_delete",
    "menu_node_update",
    "part_add",
    "part_update",
    "init_troubleshooter_db",
    "setting_mark",
    "setting_toggle",
    "admin_add",
    "admin_remove",
    "request_add",
    "request_remove",
    "user_add",
    "user_approve",
    "user_get",
    "user_notifications_get",
    "user_notifications_toggle",
    "user_revoke",
    "users_get",
    "wtgs_replace",
]
