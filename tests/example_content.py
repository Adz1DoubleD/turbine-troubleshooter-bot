IO_BOARDS = {
    "io1": {"name": "IO Board 1", "can": "Node 1"},
    "io2": {"name": "IO Board 2", "can": "Node 2"},
}


WTG_MAP = {
    "WTA01": {"serial": 1000001, "ip": "192.0.2.11"},
    "WTA02": {"serial": 1000002, "ip": "192.0.2.12"},
    "WTB01": {"serial": 1000101, "ip": "192.0.2.21"},
}

MENU = {
    "nodes": [
        {
            "id": 1,
            "parent_id": None,
            "type": "page",
            "title": "Example Note",
            "body": "Plain text shown when this item is tapped.",
            "sort_order": 1,
            "edits": [],
        },
        {
            "id": 2,
            "parent_id": None,
            "type": "submenu",
            "title": "Example Menu",
            "body": None,
            "sort_order": 2,
            "edits": [],
        },
        {
            "id": 3,
            "parent_id": 2,
            "type": "page",
            "title": "First Item",
            "body": "Text for the first item.",
            "sort_order": 1,
            "edits": [],
        },
        {
            "id": 4,
            "parent_id": 2,
            "type": "page",
            "title": "Second Item",
            "body": "Text with *Markdown*.",
            "sort_order": 2,
            "edits": [],
        },
    ],
    "attachments": [],
}
