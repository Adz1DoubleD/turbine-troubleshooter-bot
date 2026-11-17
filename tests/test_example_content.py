import ipaddress

import example_content

DOCUMENTATION_RANGES = [
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]


def strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)
    elif isinstance(obj, str):
        yield obj


def test_turbine_ips_are_documentation_addresses():
    for turbine in example_content.WTG_MAP.values():
        ip = ipaddress.ip_address(turbine["ip"])
        assert any(ip in net for net in DOCUMENTATION_RANGES), turbine["ip"]


def test_example_content_stays_small():
    assert len(example_content.WTG_MAP) <= 5
    assert len(example_content.IO_BOARDS) <= 3
    assert len(example_content.MODULES_MAP) <= 5


def test_example_content_references_no_files():
    everything = [
        example_content.MODULES_MAP,
        example_content.WTG_MAP,
        example_content.IO_BOARDS,
    ]
    assert not [s for s in strings(everything) if s.startswith("file:")]


def test_example_names_are_placeholders():
    assert all(name.startswith("WT") for name in example_content.WTG_MAP)
    assert all(
        board["name"].startswith("IO Board ")
        for board in example_content.IO_BOARDS.values()
    )
