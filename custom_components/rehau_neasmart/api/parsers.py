"""HTML scrapers for the REHAU Nea Smart 2.0 web UI.

Every function takes raw HTML and returns a typed snapshot; no I/O.

The web UI ships in 15 languages, so parsers match structure (ids, input
names, inline JS variables, trailing numbers) and never localized text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from bs4 import BeautifulSoup

from .codecs import (
    QUARTERS_PER_DAY,
    energy_level_from_device,
    operating_mode_from_device,
    room_mode_from_device,
)
from .models import (
    AlarmMessage,
    AlarmSeverity,
    Calibration,
    DailyProgram,
    Dashboard,
    FirmwareInfo,
    IOSnapshot,
    MasterIO,
    RoomCalibration,
    RoomDetail,
    RoomListEntry,
    RoomSetpoints,
    RoomSetup,
    SystemInfo,
    Topology,
    UModuleIO,
    Uptime,
    WeeklyProgram,
)

# The calibration page has at most this many room rows (air00..air19).
MAX_ZONES = 20

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_FAN_RUNNING_MARKER = 'FFF").style.fill="#DD0060"'


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _first_number(text: str | None) -> float | None:
    if not text:
        return None
    match = _NUMBER.search(text)
    return float(match[0]) if match else None


def _attr(soup: BeautifulSoup, selector: str, attr: str = "value") -> str | None:
    element = soup.select_one(selector)
    if element is None:
        return None
    value = element.get(attr)
    return value if isinstance(value, str) else None


def _input_value(soup: BeautifulSoup, name: str) -> str | None:
    return _attr(soup, f'input[name="{name}"]')


def _input_number(soup: BeautifulSoup, name: str, default: float = 0) -> float:
    value = _first_number(_input_value(soup, name))
    return default if value is None else value


def _is_checked(soup: BeautifulSoup, name: str) -> bool:
    element = soup.select_one(f'input[name="{name}"]')
    return element is not None and element.has_attr("checked")


def _selected_option(soup: BeautifulSoup, select_name: str) -> str | None:
    return _attr(soup, f'select[name="{select_name}"] option[selected]')


def _scripts(soup: BeautifulSoup) -> str:
    return "\n".join(script.get_text() for script in soup.find_all("script"))


def _js_var(scripts: str, name: str) -> float | None:
    match = re.search(rf"var\s+{name}\s*=\s*(-?\d+(?:\.\d+)?)", scripts)
    return float(match[1]) if match else None


def parse_dashboard(html: str) -> Dashboard:
    """Parse the resident dashboard at `/`.

    The single `h3.textCenter` carries the outdoor temperature behind a
    localized prefix ("Temp. esterna. 16.6", "Ext. temperature 16.6");
    only the number is taken. Installations without an outdoor sensor
    have no such heading.
    """
    soup = _soup(html)
    operating = (
        _attr(soup, "#opMode option[selected]") or _attr(soup, "#opMode option") or "5"
    )
    energy = (
        _attr(soup, "#energyL option[selected]")
        or _attr(soup, "#energyL option")
        or "2"
    )
    outdoor = soup.select_one("h3.textCenter")
    clock = soup.select_one("h2.textCenter")
    offered = [
        operating_mode_from_device(int(value))
        for option in soup.select("#opMode option")
        if isinstance(value := option.get("value"), str) and value.isdigit()
    ]
    return Dashboard(
        outdoor_temperature=_first_number(outdoor.get_text() if outdoor else None),
        clock=clock.get_text().strip() if clock else "",
        operating_mode=operating_mode_from_device(int(operating)),
        energy_level=energy_level_from_device(int(energy)),
        operating_modes=tuple(dict.fromkeys(offered)),
    )


def parse_room_list(html: str) -> list[RoomListEntry]:
    """Parse the room buttons on `/room-page.html`."""
    soup = _soup(html)
    rooms: list[RoomListEntry] = []
    for button in soup.select('form[action="room-operating.html"] button[name]'):
        zone = button.get("name")
        if not isinstance(zone, str) or not zone.isdigit():
            continue
        name = button.select_one(".labelLeft")
        temperature = button.select_one(".labelRight")
        rooms.append(
            RoomListEntry(
                zone=int(zone),
                name=name.get_text().strip() if name else "",
                temperature=_first_number(
                    temperature.get_text() if temperature else None
                ),
            )
        )
    return rooms


def parse_room_detail(html: str) -> RoomDetail:
    """Parse `/room-operating.html` for one zone.

    The fancoil button (`#FFF`) is only rendered when the room's fancoil
    is compatible with the current season; the flap shares its popup. The
    device paints that icon pink with an extra script line only while the
    fancoil motor is running.
    """
    soup = _soup(html)
    scripts = _scripts(soup)
    temperature = soup.select_one("label.labelRight.roomName")
    humidity = soup.select_one(".spanHum label.labelRight")
    setpoint = _first_number(_attr(soup, "#RSH"))
    light_input = soup.select_one('input[name="lightH"]')
    has_fan = soup.select_one("#FFF") is not None

    def js_or_setpoint(name: str) -> float | None:
        value = _js_var(scripts, name)
        return setpoint if value is None else value

    def js_int(name: str, default: int) -> int:
        value = _js_var(scripts, name)
        return default if value is None else int(value)

    return RoomDetail(
        zone=int(_input_number(soup, "zone")),
        name=(_attr(soup, "#RoomName") or "").strip(),
        temperature=_first_number(temperature.get_text() if temperature else None),
        humidity=_first_number(humidity.get_text() if humidity else None),
        setpoint=setpoint,
        setpoint_normal=js_or_setpoint("normalSetPoint"),
        setpoint_reduced=js_or_setpoint("reducedSetPoint"),
        setpoint_standby=js_or_setpoint("standbySetPoint"),
        mode=room_mode_from_device(js_int("initialState", 2)),
        program_active=js_int("programActual", 0),
        fan=js_int("initialFan", 0),
        flap=js_int("initialFla", 0),
        light=light_input is not None and light_input.get("value") == "1",
        has_light=light_input is not None,
        has_fan=has_fan,
        has_flap=has_fan,
        fan_running=_FAN_RUNNING_MARKER in scripts,
    )


def parse_room_setup(html: str) -> RoomSetup:
    """Parse the all-or-nothing form on `/room-set-up.html`."""
    soup = _soup(html)

    def number(element_id: str) -> float | None:
        return _first_number(_attr(soup, f"#{element_id}"))

    def day_program(day: int) -> int:
        selected = _selected_option(soup, f"PDay0{day}")
        # The device counts daily slots from 0; models count from 1.
        return (int(selected) if selected is not None else 0) + 1

    weekly = _selected_option(soup, "PWeek")
    return RoomSetup(
        zone=int(_input_number(soup, "zone")),
        name=(_attr(soup, "#RoomName") or "").strip(),
        setpoints=RoomSetpoints(
            normal_heating=number("HNorm"),
            reduced_heating=number("HRed"),
            standby=number("HStand"),
            normal_cooling=number("CNorm"),
            reduced_cooling=number("CRed"),
            max_heating=number("SPMax"),
            min_cooling=number("SPMin"),
        ),
        auto_start=_is_checked(soup, "Auto"),
        window_detection=_is_checked(soup, "SWOW"),
        lock=_is_checked(soup, "Lock"),
        weekly_program=int(weekly) if weekly is not None else 0,
        day_programs=tuple(day_program(day) for day in range(7)),
    )


_SEVERITIES = {
    "I": AlarmSeverity.INFO,
    "W": AlarmSeverity.WARNING,
    "E": AlarmSeverity.ERROR,
    "C": AlarmSeverity.CRITICAL,
}
_TIMESTAMP = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})")
_MESSAGE_COLUMNS = 6


def _parse_timestamp(text: str) -> datetime | None:
    """Parse "2026/3/31 11:28" into a naive datetime in the device's local time."""
    match = _TIMESTAMP.match(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute = (int(part) for part in match.groups())
    return datetime(year, month, day, hour, minute)  # noqa: DTZ001


def parse_messages(html: str) -> list[AlarmMessage]:
    """Parse the alarm table on `/messages.html`."""
    soup = _soup(html)
    messages: list[AlarmMessage] = []
    for row in soup.select('form[action="user-menu.html"] table tr'):
        cells = [cell.get_text().strip() for cell in row.find_all("td")]
        if len(cells) < _MESSAGE_COLUMNS or "/" not in cells[1]:
            continue
        index, started, severity, source, ended, code = cells[:_MESSAGE_COLUMNS]
        messages.append(
            AlarmMessage(
                index=int(index) if index.isdigit() else len(messages) + 1,
                severity=_SEVERITIES.get(severity.upper(), AlarmSeverity.INFO),
                source=source.removesuffix(":").strip(),
                code=code,
                started_at=_parse_timestamp(started),
                resolved_at=_parse_timestamp(ended),
            )
        )
    return messages


def parse_daily_program(html: str) -> DailyProgram:
    """Parse `/user-update-daily-program.html`; the device's 0-based id becomes 1-based."""
    soup = _soup(html)
    raw = _input_value(soup, "prog") or ""
    return DailyProgram(
        id=int(_input_number(soup, "idProgDay")) + 1,
        bits=tuple(
            1 if index < len(raw) and raw[index] == "1" else 0
            for index in range(QUARTERS_PER_DAY)
        ),
    )


def parse_weekly_program(html: str) -> WeeklyProgram:
    """Parse `/user-update-weekly-program.html`; daily slots become 1-based."""
    soup = _soup(html)

    def day(index: int) -> int:
        selected = _selected_option(soup, f"PDay{index}")
        return (int(selected) if selected is not None else 0) + 1

    return WeeklyProgram(
        id=int(_input_number(soup, "weeklyProgram", default=1)),
        days=tuple(day(index) for index in range(7)),
    )


def parse_calibration(html: str) -> Calibration:
    """Parse `/installer-adjustementOffset.html` (installer only)."""
    soup = _soup(html)
    rooms: dict[int, RoomCalibration] = {}
    for zone in range(MAX_ZONES):
        air = _input_value(soup, f"air{zone:02d}")
        humidity = _input_value(soup, f"humi{zone:02d}")
        if air is None and humidity is None:
            continue
        rooms[zone] = RoomCalibration(
            zone=zone,
            temperature_offset=_first_number(air) or 0.0,
            humidity_offset=_first_number(humidity),
        )
    return Calibration(
        outdoor_offset=_first_number(_input_value(soup, "out00")), rooms=rooms
    )


# "<N> <word> <N> <word> <N> <word>", where a word is any run of
# non-digit, non-space characters so "Year(s)" and "Tag(e)" match too.
_UPTIME = re.compile(r"(\d+)\s+[^\d\s]+\s+(\d+)\s+[^\d\s]+\s+(\d+)\s+[^\d\s]+")


def parse_uptime(html: str) -> Uptime:
    """Parse the controller uptime on `/installer-system-statistics.html`."""
    text = re.sub(r"\s+", " ", _soup(html).get_text(" "))
    match = _UPTIME.search(text)
    if match is None:
        return Uptime(years=0, days=0, hours=0)
    return Uptime(years=int(match[1]), days=int(match[2]), hours=int(match[3]))


def parse_topology(html: str) -> Topology:
    """Parse the bus topology on `/diagSett.html`."""
    soup = _soup(html)

    def count(name: str) -> int:
        return int(_input_number(soup, name))

    return Topology(
        base_modules=count("ccDiag"),
        r_modules=count("emr"),
        u_modules=count("emu"),
        rooms=count("room"),
        mixed_circuits=count("mc"),
        dehumidifiers=count("dehu"),
    )


def _after_colon(text: str) -> list[str]:
    _, _, rest = text.partition(":")
    return rest.split()


def _number_list(text: str) -> tuple[float, ...]:
    values: list[float] = []
    for part in _after_colon(text):
        try:
            values.append(float(part.replace("°C", "").replace("%", "")))
        except ValueError:
            continue
    return tuple(values)


def _analog_list(text: str) -> tuple[float | None, ...]:
    values: list[float | None] = []
    for part in _after_colon(text):
        if part.startswith("--"):
            values.append(None)
            continue
        try:
            values.append(float(part.replace("°C", "")))
        except ValueError:
            continue
    return tuple(values)


_RZ = re.compile(r"RZ\s*1\s*-\s*8", re.IGNORECASE)
_RELAY = re.compile(r"RELAY\s*1\s*-\s*4", re.IGNORECASE)
_DI = re.compile(r"DI\s*1\s*-\s*4", re.IGNORECASE)
_AI = re.compile(r"AI\s*1\s*-\s*4", re.IGNORECASE)
_AO = re.compile(r"^\s*AO\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_TRAILING_INDEX = re.compile(r"(\d+)\s*$")


@dataclass(slots=True)
class _Channels:
    rz: tuple[float, ...] = ()
    relay: tuple[float, ...] = ()
    di: tuple[float, ...] = ()
    ai: tuple[float | None, ...] = ()
    ao: float = 0.0


def parse_io(html: str) -> IOSnapshot:
    """Parse `/installer-inputoutput.html` (installer only).

    Labels are attributed to the most recent `h3` section heading. The
    master section is the one whose heading says "master"; every other
    heading ending in a number is U-module <number>, whatever the
    localized prefix.
    """
    soup = _soup(html)
    master = _Channels()
    umodules: dict[int, _Channels] = {}
    section: _Channels | None = None

    for element in soup.find_all(["h3", "label"]):
        text = element.get_text()
        if element.name == "h3":
            heading = text.strip()
            if "master" in heading.lower():
                section = master
            elif match := _TRAILING_INDEX.search(heading):
                section = umodules[int(match[1])] = _Channels()
            continue
        if section is None:
            continue
        if _RZ.search(text) and section is master:
            section.rz = _number_list(text)
        elif _RELAY.search(text):
            section.relay = _number_list(text)
        elif _DI.search(text):
            section.di = _number_list(text)
        elif _AI.search(text) and section is not master:
            section.ai = _analog_list(text)
        elif (match := _AO.match(text)) and section is not master:
            section.ao = float(match[1])

    return IOSnapshot(
        master=MasterIO(rz=master.rz, relay=master.relay, di=master.di),
        umodules={
            index: UModuleIO(
                relay=channels.relay, di=channels.di, ai=channels.ai, ao=channels.ao
            )
            for index, channels in umodules.items()
        },
    )


_UNIQUE_CODE = re.compile(r"Unique code\s*:\s*([0-9a-f]+)\b", re.IGNORECASE)
_MASTER_VERSION = re.compile(r"Master:\s*([\d.]+)")
_UMODULE_VERSION = re.compile(r"\b(\d+)\D*:\s*([\d.\s]+?)\s*$")
_WEB_VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?)\s*$")


def parse_system_info(html: str) -> SystemInfo:
    """Parse `/user-config-installer.html`.

    "Unique code" and "Master:" are untranslated technical labels in
    every language pack. The web and U-module version labels carry a
    localized prefix, so they are told apart by shape: a number, then a
    colon, then a version ("Modulo-U 0: 1.2", "U-Module 0 version: 1.2")
    is U-module N; a lone trailing "X.Y" is the web pages version.
    """
    soup = _soup(html)
    # Separate element texts: the code's label is directly followed by
    # another label ("6W"), and gluing them would extend the hex run.
    text = soup.get_text(" ")
    unique_code = _UNIQUE_CODE.search(text)
    master = _MASTER_VERSION.search(text)
    umodules: dict[int, str] = {}
    web = ""
    for label in soup.find_all("label"):
        label_text = label.get_text().strip()
        if not label_text or "master" in label_text.lower():
            continue
        if match := _UMODULE_VERSION.search(label_text):
            umodules[int(match[1])] = re.sub(r"\s+", "", match[2])
        elif not web and (match := _WEB_VERSION.search(label_text)):
            web = match[1]
    return SystemInfo(
        unique_code=unique_code[1].lower() if unique_code else "",
        firmware=FirmwareInfo(
            master=master[1] if master else "", web=web, umodules=umodules
        ),
        season_start=_attr(soup, "#HCP2") or "10-01",
        season_end=_attr(soup, "#HCP3") or "05-01",
        outdoor_offset=_first_number(_attr(soup, "#HLS")) or 0.0,
    )
