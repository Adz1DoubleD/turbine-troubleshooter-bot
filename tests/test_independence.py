import ast
import pathlib
from types import SimpleNamespace

import pytest

import turbine_troubleshooter
from turbine_troubleshooter.blocks import handle_block
from turbine_troubleshooter.settings import SETTINGS, setup

PACKAGE = pathlib.Path(turbine_troubleshooter.__file__).parent
MAIN_BOT_MODULES = {"bot", "config", "services", "media", "main"}


def outside_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            if name.split(".")[0] in MAIN_BOT_MODULES:
                yield f"{path.relative_to(PACKAGE.parent)}:{node.lineno} imports {name}"


def test_troubleshooter_imports_nothing_from_the_main_bot():
    found = [hit for f in sorted(PACKAGE.rglob("*.py")) for hit in outside_imports(f)]

    assert found == []


def test_setup_rejects_unknown_settings():
    with pytest.raises(TypeError, match="not_a_setting"):
        setup(not_a_setting=1)


def test_setup_applies_known_settings(monkeypatch):
    monkeypatch.setattr(SETTINGS, "timezone", "UTC")

    setup(timezone="Europe/Paris")

    assert SETTINGS.timezone == "Europe/Paris"


def menu_callbacks(block):
    return [
        b.callback_data for row in block["reply_markup"].inline_keyboard for b in row
    ]


@pytest.mark.parametrize("buoy, shown", [(None, False), ("BUOY1", True)])
@pytest.mark.asyncio
async def test_weather_button_only_when_configured(monkeypatch, buoy, shown):
    monkeypatch.setattr(SETTINGS, "cefas_buoy", buoy)
    context = SimpleNamespace(
        bot_data={"is_troubleshooter": True, "codes": {}, "parts": []},
        user_data={"is_admin": False},
    )

    block = await handle_block(context)

    assert ("troubleshooter:weather" in menu_callbacks(block)) is shown
