import ast
from pathlib import Path

import turbine_troubleshooter

PACKAGE = Path(turbine_troubleshooter.__file__).parent
ALLOWED = ("cancel", "ignore")


def callback_literals():
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.keyword) or node.arg != "callback_data":
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                yield path.name, node.lineno, value.value
            elif isinstance(value, ast.JoinedStr) and value.values:
                first = value.values[0]
                if isinstance(first, ast.Constant):
                    yield path.name, node.lineno, first.value


def test_every_button_belongs_to_the_troubleshooter():
    found = list(callback_literals())
    wrong = [
        f"{name}:{line} {data!r}"
        for name, line, data in found
        if not data.startswith("troubleshooter:") and data not in ALLOWED
    ]

    assert len(found) > 50
    assert wrong == []
