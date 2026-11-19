from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import aiohttp
import sentry_sdk
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from turbine_troubleshooter.settings import SETTINGS

WINDQUEST_URL = "https://api.weatherquest.co.uk/API/WindQuest/API-Forecast"
WINDQUEST_TIMEOUT = 30
CEFAS_RESULTS_URL = (
    "https://wavenet-api.cefas.co.uk/api/Detail/Results/{buoy}/INT?showForecast=true"
)
CEFAS_CHART_URL = "https://wavenet-api.cefas.co.uk/api/Chart/Line/{buoy}/INT"
CEFAS_PAGE_URL = "https://wavenet.cefas.co.uk/details/{buoy}/INT"
CEFAS_HEADERS = {
    "Referer": "https://wavenet.cefas.co.uk/",
    "User-Agent": "Mozilla/5.0",
}
HEADINGS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def is_enabled():
    return bool(SETTINGS.cefas_buoy or SETTINGS.windquest_api_key)


async def fetch(url, headers=None, params=None, timeout=5):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 200:
                    res = await response.json()
                    return (
                        res if isinstance(res, dict) else {"value": res, "status": 200}
                    )
                return {"error": True, "status": response.status}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"error": True, "status": 999, "message": str(e)}


async def fetch_bytes(url, headers=None, params=None, timeout=5):
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(url, headers=headers, params=params) as response:
                return await response.read() if response.status == 200 else None
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return None


def degrees_to_heading(deg):
    return HEADINGS[round(deg / 22.5) % 16]


def get_safety_emoji(value, kind="wave"):
    if kind == "wind":
        if value > 18:
            return "🔴"
        if value >= 12:
            return "🟡"
        return "🟢"
    if value > 1.3:
        return "🔴"
    if value >= 0.8:
        return "🟡"
    return "🟢"


def parse_dt(raw_str):
    if "T" in raw_str:
        dt = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, True
    dt = datetime.strptime(raw_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt, False


async def get_cefas_data(brief: bool = False, hours: int = 6, tomorrow: bool = False):
    buoy = SETTINGS.cefas_buoy
    if not buoy:
        return None, None

    text = "🌊 *Sea State*\n └ ⚠️ Service unavailable\n"
    image = None

    res = await fetch(
        CEFAS_RESULTS_URL.format(buoy=buoy), headers=CEFAS_HEADERS, timeout=20
    )
    data = None if res.get("error") else res.get("value")

    if data is not None:
        local = ZoneInfo(SETTINGS.timezone)

        rows = []
        for r in data:
            vals = {}
            for p in r.get("results", []):
                try:
                    vals[p["identifier"]] = float(p["value"])
                except (TypeError, ValueError, KeyError):
                    pass
            if "Hm0" not in vals:
                continue
            dt, _ = parse_dt(r["timestamp"])
            dt = dt.astimezone(local)
            rows.append((dt, r.get("isForecast", False), vals))

        obs = sorted((x for x in rows if not x[1]), key=lambda x: x[0])
        fc = sorted((x for x in rows if x[1]), key=lambda x: x[0])

        def line(dt, v):
            h = round(v["Hm0"], 2)
            head = degrees_to_heading(v["W_PDIR"]) if "W_PDIR" in v else "N/A"
            return f" ├ {dt:%H:%M} {get_safety_emoji(h)} {h}m · {head}"

        if tomorrow:
            target = (datetime.now(local) + timedelta(days=1)).date()
            lines = ["🌊 *Sea State — Tomorrow*  _(Met Office)_"]
            count = 0
            for dt, _, v in fc:
                if dt.date() != target or dt.hour < 6 or dt.hour % 3:
                    continue
                lines.append(line(dt, v))
                count += 1
                if count >= hours:
                    break
            text = (
                "🌊 *Sea State — Tomorrow*\n └ ⚠️ No forecast available.\n"
                if len(lines) == 1
                else "\n".join(
                    [lines[0]] + lines[1:-1] + [lines[-1].replace(" ├ ", " └ ", 1)]
                )
                + "\n"
            )

        elif obs or fc:
            lines = ["🌊 *Sea State*  _(Cefas / Met Office)_"]
            if obs:
                dt, _, v = obs[-1]
                h = round(v["Hm0"], 2)
                head = degrees_to_heading(v["W_PDIR"]) if "W_PDIR" in v else "N/A"
                lines.append(
                    f" ├ Now: {get_safety_emoji(h)} {h}m · {head}  _(buoy {dt:%H:%M})_"
                )

            now_hour = datetime.now(local).replace(minute=0, second=0, microsecond=0)
            count = 0
            for dt, _, v in fc:
                if dt <= now_hour:
                    continue
                lines.append(line(dt, v))
                count += 1
                if count >= hours:
                    break

            lines[-1] = lines[-1].replace(" ├ ", " └ ", 1)
            text = "\n".join(lines) + "\n"
        else:
            text = "🌊 *Sea State*\n └ ⚠️ No data available right now.\n"

    if not brief:
        now = datetime.now(ZoneInfo("UTC"))
        params = {
            "parameterCode": "Hm0",
            "start": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            "end": (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S"),
            "showForecast": "true",
            "showWQ": "true",
            "multi": "false",
        }
        img = await fetch_bytes(
            CEFAS_CHART_URL.format(buoy=buoy),
            headers=CEFAS_HEADERS,
            params=params,
            timeout=20,
        )
        if img:
            image = BytesIO(img)
            image.name = "sea_state.png"

    return text, image


async def get_windquest_data(
    hours: int = 6, location: str | None = None, tomorrow: bool = False
):
    if not (SETTINGS.windquest_api_key and SETTINGS.windquest_api_token):
        return None
    location = location or SETTINGS.windquest_location

    data = await fetch(
        WINDQUEST_URL,
        params={
            "APIKey": SETTINGS.windquest_api_key,
            "APIToken": SETTINGS.windquest_api_token,
            "Rand": "0",
        },
        timeout=WINDQUEST_TIMEOUT,
    )

    if not data or data.get("error"):
        return None

    forecasts = data.get("Forecast", [])
    loc = (
        (
            location
            and next((f for f in forecasts if f["Location"]["Name"] == location), None)
        )
        or next(
            (f for f in forecasts if f["Location"].get("MainLocation") == "1"), None
        )
        or (forecasts[0] if forecasts else None)
    )
    if not loc:
        return None

    wqf = loc["WindQuestForecast"]
    times = wqf["ValidTime"].split(",")
    spd = wqf["WindSpeed_ms"].split(",")
    gst = wqf["GustSpeed_ms"].split(",")
    dirs = wqf["WindDirection"].split(",")
    lgt = wqf["LightningRisk"].split(",")

    local = ZoneInfo(SETTINGS.timezone)
    now = datetime.now(local).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    target = (now + timedelta(days=1)).date() if tomorrow else None

    header = (
        "💨 *Wind — Tomorrow*" if tomorrow else f"💨 *Wind — {loc['Location']['Name']}*"
    )
    lines = [f"{header}  _(WindQuest)_"]
    rank = {"Yellow": 1, "Amber": 2, "Red": 3}
    windows = []
    run = None
    count = 0
    for t, s, g, d, lr in zip(times, spd, gst, dirs, lgt):
        try:
            dt = datetime.strptime(t.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if tomorrow:
            if dt.date() != target or dt.hour < 6 or dt.hour % 3:
                continue
        elif dt < now:
            continue
        ms = round(float(s), 1)
        gms = round(float(g), 1)
        lines.append(
            f" ├ {dt:%H:%M} {get_safety_emoji(ms, 'wind')} {ms}m/s (gust {gms}) · {d}"
        )
        lvl = lr.strip()
        if lvl in rank:
            if run is None:
                run = [dt, dt, lvl]
            else:
                run[1] = dt
                if rank[lvl] > rank[run[2]]:
                    run[2] = lvl
        elif run:
            windows.append(run)
            run = None
        count += 1
        if count >= hours:
            break
    if run:
        windows.append(run)

    if len(lines) > 1:
        lines[-1] = lines[-1].replace(" ├ ", " └ ", 1)
        wind_text = "\n".join(lines) + "\n"
    else:
        wind_text = ""

    colour = {"Yellow": "🟡", "Amber": "🟠", "Red": "🔴"}
    wlines = []
    for start, end, lvl in windows:
        span = f"{start:%H:%M}" if start == end else f"{start:%H:%M}–{end:%H:%M}"
        wlines.append(f"*⚡ Lightning risk {colour[lvl]} {span}*")
    lightning_text = "\n".join(wlines) + "\n" if wlines else ""

    utc = ZoneInfo("UTC")
    now_local = datetime.now(local)
    events = []
    for x in data.get("TidalForecast", []):
        tide = x.get("Tides", {})
        try:
            dt = (
                datetime.strptime(tide["ValidDate"], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=utc)
                .astimezone(local)
            )
            h = round(float(tide["Height"]), 1)
        except (KeyError, ValueError, TypeError):
            continue
        kind = "High" if tide.get("EventType") == "HighWater" else "Low"
        events.append((dt, kind, h))
    events.sort(key=lambda e: e[0])

    if tomorrow:
        picks = [e for e in events if e[0].date() == target]
    else:
        nh = next((e for e in events if e[1] == "High" and e[0] > now_local), None)
        nl = next((e for e in events if e[1] == "Low" and e[0] > now_local), None)
        picks = sorted([e for e in (nh, nl) if e], key=lambda e: e[0])

    if picks:
        tlines = [
            "🌙 *Tides — Tomorrow*  _(WindQuest)_"
            if tomorrow
            else "🌙 *Tides*  _(WindQuest)_"
        ]
        for dt, kind, h in picks:
            tlines.append(f" ├ {kind} {dt:%H:%M} · {h}m")
        tlines[-1] = tlines[-1].replace(" ├ ", " └ ", 1)
        tide_text = "\n".join(tlines) + "\n"
    else:
        tide_text = ""

    out = tide_text
    if wind_text:
        out += ("\n" if out else "") + wind_text
    if lightning_text:
        out += "\n" + lightning_text
    return out or None


async def get_windquest_service() -> bool:
    if not (SETTINGS.windquest_api_key and SETTINGS.windquest_api_token):
        return False

    data = await fetch(
        WINDQUEST_URL,
        params={
            "APIKey": SETTINGS.windquest_api_key,
            "APIToken": SETTINGS.windquest_api_token,
            "Rand": "0",
        },
        timeout=WINDQUEST_TIMEOUT,
    )
    return bool(data) and not data.get("error") and bool(data.get("Forecast"))


async def get_weather_data(tomorrow: bool = False, brief: bool = False):
    sea, image = await get_cefas_data(brief=brief, tomorrow=tomorrow)
    wind = await get_windquest_data(tomorrow=tomorrow)

    parts = [p for p in (sea, wind) if p]
    if not parts:
        return "🌊 *Weather*\n └ ⚠️ No weather data available right now.\n", None

    return "\n".join(parts) + "\n", image


async def weather_block(
    is_tomorrow=False,
    brief=False,
    base="troubleshooter:weather",
    back=("🔙 Back", "troubleshooter:home"),
    close=False,
):
    text, image = await get_weather_data(tomorrow=is_tomorrow, brief=brief)

    today, tomorrow = base, f"{base}:tomorrow"
    rows = [
        [
            InlineKeyboardButton(
                "☀️ View Today" if is_tomorrow else "📅 View Tomorrow",
                callback_data=today if is_tomorrow else tomorrow,
            )
        ]
    ]
    if SETTINGS.cefas_buoy:
        rows.append(
            [
                InlineKeyboardButton(
                    "🌍 Cefas Wavenet",
                    url=CEFAS_PAGE_URL.format(buoy=SETTINGS.cefas_buoy),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "🔄 Refresh", callback_data=tomorrow if is_tomorrow else today
            )
        ]
    )
    if back:
        rows.append([InlineKeyboardButton(back[0], callback_data=back[1])])
    if close:
        rows.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])

    return {
        "text": text,
        "image": image,
        "reply_markup": InlineKeyboardMarkup(rows),
        "parse_mode": "Markdown",
    }


async def send_block(query, block):
    message = query.message

    if block.get("image"):
        try:
            await message.delete()
        except Exception:
            pass
        await message.reply_photo(
            photo=block["image"],
            caption=block["text"],
            parse_mode="Markdown",
            reply_markup=block["reply_markup"],
        )
        return

    text_args = {
        "text": block["text"],
        "reply_markup": block["reply_markup"],
        "parse_mode": block.get("parse_mode", "Markdown"),
        "disable_web_page_preview": True,
    }
    if message.text is not None:
        await query.edit_message_text(**text_args)
        return

    await message.delete()
    await message.reply_text(**text_args)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    block = await weather_block(is_tomorrow=query.data.endswith(":tomorrow"))
    await send_block(query, block)
