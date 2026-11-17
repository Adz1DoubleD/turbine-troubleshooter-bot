IO_BOARDS = {
    "io1": {"name": "IO Board 1", "can": "Node 1"},
    "io2": {"name": "IO Board 2", "can": "Node 2"},
}


WTG_MAP = {
    "WTA01": {"serial": 1000001, "ip": "192.0.2.11"},
    "WTA02": {"serial": 1000002, "ip": "192.0.2.12"},
    "WTB01": {"serial": 1000101, "ip": "192.0.2.21"},
}

MODULES_MAP = {
    "Example Note": "Plain text shown when this item is tapped.",
    "Example Menu": {
        "menu": {
            "First Item": "Text for the first item.",
            "Second Item": {"text": "Text with *Markdown*."},
        }
    },
}
