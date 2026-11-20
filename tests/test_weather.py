import pytest
from freezegun import freeze_time

import turbine_troubleshooter.weather as wq

FROZEN = "2026-10-22 18:00:00"


def wqf(times, speeds, gusts, dirs, lightning):
    return {
        "ValidTime": ",".join(times),
        "WindSpeed_ms": ",".join(str(s) for s in speeds),
        "GustSpeed_ms": ",".join(str(g) for g in gusts),
        "WindDirection": ",".join(dirs),
        "LightningRisk": ",".join(lightning),
    }


def loc(name, forecast, main="0"):
    return {
        "Location": {"Name": name, "MainLocation": main},
        "WindQuestForecast": forecast,
    }


def tide(valid_utc, height, kind):
    return {"Tides": {"ValidDate": valid_utc, "Height": str(height), "EventType": kind}}


def payload(forecasts, tides=None):
    return {"Forecast": forecasts, "TidalForecast": tides or []}


def hours_today(*hh):
    return [f"2026-10-22 {h:02d}:00" for h in hh]


@pytest.fixture
def set_payload(monkeypatch):
    monkeypatch.setattr(wq.SETTINGS, "windquest_api_key", "k")
    monkeypatch.setattr(wq.SETTINGS, "windquest_api_token", "t")

    def _set(data):
        async def fake_fetch(*a, **k):
            return data

        monkeypatch.setattr(wq, "fetch", fake_fetch)

    return _set


@pytest.mark.asyncio
async def test_wind_today_skips_past_and_limits_to_hours(set_payload):
    times = hours_today(17, 18, 19, 20, 21, 22, 23)
    f = wqf(times, [10] * 7, [12] * 7, ["SW"] * 7, ["Green"] * 7)
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data(hours=3)
    assert "💨 *Wind — Site 1*" in out
    assert "19:00" in out and "20:00" in out and "21:00" in out
    assert "17:00" not in out and "18:00" not in out
    assert "22:00" not in out
    assert " └ 21:00" in out


@pytest.mark.asyncio
async def test_wind_tomorrow_is_three_hourly_from_six(set_payload):
    times = [f"2026-10-23 {h:02d}:00" for h in (5, 6, 7, 8, 9, 12, 15)]
    f = wqf(times, [10] * 7, [12] * 7, ["SW"] * 7, ["Green"] * 7)
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data(tomorrow=True)
    assert "💨 *Wind — Tomorrow*" in out
    for h in ("06:00", "09:00", "12:00", "15:00"):
        assert h in out
    assert "05:00" not in out and "07:00" not in out and "08:00" not in out


@pytest.mark.asyncio
async def test_no_lightning_line_when_all_green(set_payload):
    f = wqf(hours_today(19, 20), [10, 10], [12, 12], ["SW", "SW"], ["Green", "Green"])
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data()
    assert "Lightning risk" not in out


@pytest.mark.asyncio
async def test_lightning_single_hour_has_no_range(set_payload):
    f = wqf(hours_today(19, 20), [10, 10], [12, 12], ["SW", "SW"], ["Yellow", "Green"])
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data()
    assert "*⚡ Lightning risk 🟡 19:00*" in out
    assert "19:00–" not in out


@pytest.mark.asyncio
async def test_lightning_window_shows_peak_level(set_payload):
    f = wqf(
        hours_today(19, 20, 21),
        [10, 10, 10],
        [12, 12, 12],
        ["SW"] * 3,
        ["Yellow", "Amber", "Green"],
    )
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data()
    assert "*⚡ Lightning risk 🟠 19:00–20:00*" in out
    assert "🟡" not in out


@pytest.mark.asyncio
async def test_lightning_two_windows_separate_lines(set_payload):
    times = hours_today(19, 20, 21, 22, 23) + ["2026-10-23 00:00"]
    f = wqf(
        times,
        [10] * 6,
        [12] * 6,
        ["SW"] * 6,
        ["Yellow", "Yellow", "Green", "Red", "Red", "Green"],
    )
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data()
    assert "*⚡ Lightning risk 🟡 19:00–20:00*" in out
    assert "*⚡ Lightning risk 🔴 22:00–23:00*" in out


@pytest.mark.asyncio
async def test_lightning_window_still_emitted_when_open_at_limit(set_payload):
    f = wqf(
        hours_today(19, 20, 21),
        [10] * 3,
        [12] * 3,
        ["SW"] * 3,
        ["Green", "Yellow", "Yellow"],
    )
    set_payload(payload([loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data(hours=3)
    assert "*⚡ Lightning risk 🟡 20:00–21:00*" in out


@pytest.mark.asyncio
async def test_tides_today_next_high_and_low_chronological(set_payload):
    f = wqf(hours_today(19), [10], [12], ["SW"], ["Green"])
    tides = [
        tide("2026-10-22 13:57:00", "1.47", "LowWater"),
        tide("2026-10-22 20:05:00", "4.14", "HighWater"),
        tide("2026-10-23 02:30:00", "1.62", "LowWater"),
    ]
    set_payload(payload([loc("Site 1", f)], tides))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data()
    assert "🌙 *Tides*" in out
    assert "High 21:05 · 4.1m" in out
    assert "Low 03:30 · 1.6m" in out
    assert out.index("High 21:05") < out.index("Low 03:30")


@pytest.mark.asyncio
async def test_tides_tomorrow_lists_that_day_only(set_payload):
    f = wqf(
        ["2026-10-23 06:00", "2026-10-23 09:00"],
        [10, 10],
        [12, 12],
        ["SW", "SW"],
        ["Green", "Green"],
    )
    tides = [
        tide("2026-10-22 20:05:00", "4.14", "HighWater"),
        tide("2026-10-23 07:15:00", "4.01", "HighWater"),
        tide("2026-10-23 13:57:00", "1.47", "LowWater"),
    ]
    set_payload(payload([loc("Site 1", f)], tides))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data(tomorrow=True)
    assert "🌙 *Tides — Tomorrow*" in out
    assert "High 08:15" in out and "Low 14:57" in out
    assert "21:05" not in out


@pytest.mark.asyncio
async def test_named_location_wins(set_payload):
    f = wqf(hours_today(19), [10], [12], ["SW"], ["Green"])
    set_payload(payload([loc("Main Site", f, main="1"), loc("Site 1", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data(location="Site 1")
    assert "💨 *Wind — Site 1*" in out


@pytest.mark.asyncio
async def test_falls_back_to_main_location(set_payload):
    f = wqf(hours_today(19), [10], [12], ["SW"], ["Green"])
    set_payload(payload([loc("Main Site", f, main="1"), loc("Other", f)]))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data(location="DOESNOTEXIST")
    assert "💨 *Wind — Main Site*" in out


@pytest.mark.asyncio
async def test_assembly_order_is_tides_wind_lightning(set_payload):
    f = wqf(hours_today(19, 20), [13, 13], [16, 16], ["SW", "SW"], ["Yellow", "Yellow"])
    tides = [
        tide("2026-10-22 20:05:00", "4.14", "HighWater"),
        tide("2026-10-23 02:30:00", "1.62", "LowWater"),
    ]
    set_payload(payload([loc("Site 1", f)], tides))
    with freeze_time(FROZEN):
        out = await wq._get_windquest_data()
    assert out.startswith("🌙")
    assert out.index("🌙") < out.index("💨") < out.index("⚡")
    assert "\n\n💨" in out
    assert "\n\n*⚡" in out


@pytest.mark.asyncio
async def test_none_on_fetch_error(set_payload):
    set_payload({"error": True})
    with freeze_time(FROZEN):
        assert await wq._get_windquest_data() is None


@pytest.mark.asyncio
async def test_none_on_empty_forecast(set_payload):
    set_payload(payload([]))
    with freeze_time(FROZEN):
        assert await wq._get_windquest_data() is None


@pytest.mark.asyncio
async def test_none_without_credentials(monkeypatch):
    monkeypatch.setattr(wq.SETTINGS, "windquest_api_key", "")
    monkeypatch.setattr(wq.SETTINGS, "windquest_api_token", "")
    assert await wq._get_windquest_data() is None


@pytest.mark.parametrize(
    "buoy, key, enabled",
    [(None, None, False), ("BUOY1", None, True), (None, "k", True)],
)
def test_weather_enabled_only_when_configured(monkeypatch, buoy, key, enabled):
    monkeypatch.setattr(wq.SETTINGS, "cefas_buoy", buoy)
    monkeypatch.setattr(wq.SETTINGS, "windquest_api_key", key)

    assert wq.is_enabled() is enabled


@pytest.mark.asyncio
async def test_cefas_off_without_buoy(monkeypatch):
    async def must_not_fetch(*a, **k):
        raise AssertionError("no buoy configured, must not fetch")

    monkeypatch.setattr(wq.SETTINGS, "cefas_buoy", None)
    monkeypatch.setattr(wq, "fetch", must_not_fetch)

    assert await wq._get_cefas_data() == (None, None)


@pytest.mark.asyncio
async def test_cefas_reads_buoy_and_forecast(monkeypatch):
    monkeypatch.setattr(wq.SETTINGS, "cefas_buoy", "BUOY1")
    monkeypatch.setattr(wq.SETTINGS, "timezone", "UTC")
    urls = []

    async def fake_fetch(url, **k):
        urls.append(url)
        return {
            "value": [
                {
                    "timestamp": "2026-10-22T17:30:00Z",
                    "isForecast": False,
                    "results": [
                        {"identifier": "Hm0", "value": "0.5"},
                        {"identifier": "W_PDIR", "value": "225"},
                    ],
                },
                {
                    "timestamp": "2026-10-22T20:00:00Z",
                    "isForecast": True,
                    "results": [{"identifier": "Hm0", "value": "1.4"}],
                },
            ]
        }

    async def fake_bytes(*a, **k):
        return b"png"

    monkeypatch.setattr(wq, "fetch", fake_fetch)
    monkeypatch.setattr(wq, "_fetch_bytes", fake_bytes)
    with freeze_time(FROZEN):
        text, image = await wq._get_cefas_data()

    assert "BUOY1" in urls[0]
    assert "Now: 🟢 0.5m · SW" in text
    assert "20:00 🔴 1.4m" in text
    assert image.name == "sea_state.png"


@pytest.mark.asyncio
async def test_no_weather_data_message(monkeypatch):
    async def nothing(**k):
        return None, None

    async def no_wind(**k):
        return None

    monkeypatch.setattr(wq, "_get_cefas_data", nothing)
    monkeypatch.setattr(wq, "_get_windquest_data", no_wind)

    text, image = await wq._get_weather_data()

    assert "No weather data available" in text
    assert image is None


def buttons(block):
    return [
        (b.text, b.callback_data or b.url)
        for row in block["reply_markup"].inline_keyboard
        for b in row
    ]


@pytest.mark.parametrize("buoy", [None, "BUOY1"])
@pytest.mark.asyncio
async def test_weather_block_keyboard(monkeypatch, buoy):
    async def data(**k):
        return "WEATHER", None

    monkeypatch.setattr(wq, "_get_weather_data", data)
    monkeypatch.setattr(wq.SETTINGS, "cefas_buoy", buoy)

    block = await wq.weather_block()

    expected = [("📅 View Tomorrow", "troubleshooter:weather:tomorrow")]
    if buoy:
        expected.append(
            ("🌍 Cefas Wavenet", "https://wavenet.cefas.co.uk/details/BUOY1/INT")
        )
    expected += [
        ("🔄 Refresh", "troubleshooter:weather"),
        ("🔙 Back", "troubleshooter:home"),
    ]
    assert block["text"] == "WEATHER"
    assert buttons(block) == expected


@pytest.mark.asyncio
async def test_weather_block_for_host_bot(monkeypatch):
    async def data(**k):
        return "WEATHER", None

    monkeypatch.setattr(wq, "_get_weather_data", data)

    block = await wq.weather_block(
        is_tomorrow=True, base="weather:work", back=None, close=True
    )

    assert buttons(block) == [
        ("☀️ View Today", "weather:work"),
        ("🔄 Refresh", "weather:work:tomorrow"),
        ("❌ Close", "cancel"),
    ]


@pytest.mark.parametrize(
    "data, tomorrow",
    [
        ("troubleshooter:weather", False),
        ("troubleshooter:weather:tomorrow", True),
    ],
)
@pytest.mark.asyncio
async def test_handle_button_sends_block(monkeypatch, data, tomorrow):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    seen = {}

    async def block(is_tomorrow=False, **k):
        seen["tomorrow"] = is_tomorrow
        return {"text": "W", "image": None, "reply_markup": None}

    monkeypatch.setattr(wq, "weather_block", block)
    query = SimpleNamespace(
        data=data, message=SimpleNamespace(text="old"), edit_message_text=AsyncMock()
    )

    await wq.handle_button(SimpleNamespace(callback_query=query), SimpleNamespace())

    assert seen["tomorrow"] is tomorrow
    assert query.edit_message_text.await_args.kwargs["text"] == "W"
