"""Typed reads and writes against one REHAU Nea Smart 2.0 base station.

Installer mode is a single global flag on the device: no cookie, no
per-client scope. POSTing `instPart=<code>` to `/menu.html` turns it on,
GET `/user-menu.html` turns it off, and every client on the device's
network sees installer pages in between. Like rehau-bridge, this class
turns it on once and keeps it on until `close()`, so each installer read
is one request instead of login, read, logout.
"""

from __future__ import annotations

from collections.abc import Sequence

from .client import RehauClient
from .codecs import (
    QUARTERS_PER_DAY,
    energy_level_to_device,
    operating_mode_to_device,
    room_mode_to_form,
    setpoint_to_form,
)
from .exceptions import RehauInstallerError, RehauInvalidDeviceError
from .forms import DeviceForm, apply_changes, form_body, parse_form
from .models import (
    AlarmMessage,
    Calibration,
    DailyProgram,
    Dashboard,
    EnergyLevel,
    InstallerSettings,
    InstallerSettingsGroup,
    IOSnapshot,
    OperatingMode,
    RoomDetail,
    RoomListEntry,
    RoomMode,
    RoomSetup,
    SystemInfo,
    Topology,
    Uptime,
    WeeklyProgram,
)
from .parsers import (
    parse_calibration,
    parse_daily_program,
    parse_dashboard,
    parse_io,
    parse_messages,
    parse_room_detail,
    parse_room_list,
    parse_room_setup,
    parse_system_info,
    parse_topology,
    parse_uptime,
    parse_weekly_program,
)
from .settings import SETTINGS_ACTION, SETTINGS_PAGES, settings_from_form

DAILY_PROGRAMS = 10
WEEKLY_PROGRAMS = 5
DAYS_PER_WEEK = 7

_ROOM_SETUP_FLAGS = {"lock": "Lock", "auto_start": "Auto", "window_detection": "SWOW"}
_CALIBRATION_PAGE = "/installer-adjustementOffset.html"
_CALIBRATION_ACTION = "installer-diagnosis.html"


def _check_id(kind: str, value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"{kind} must be 1..{maximum}, got {value}")


class RehauDevice:
    """One base station, reached through a RehauClient."""

    def __init__(self, client: RehauClient, installer_code: str | None = None) -> None:
        """Wrap a client; without an installer code, installer reads raise."""
        self._client = client
        self._installer_code = installer_code or None
        self._installer_open = False

    @property
    def has_installer(self) -> bool:
        """Return True when an installer code is configured."""
        return self._installer_code is not None

    @property
    def installer_open(self) -> bool:
        """Return True while this instance holds installer mode on."""
        return self._installer_open

    # ─── installer session ───────────────────────────────────────

    async def open_installer(self) -> None:
        """Turn installer mode on, once."""
        if self._installer_code is None:
            raise RehauInstallerError("no installer code configured")
        if self._installer_open:
            return
        await self._client.post_form("/menu.html", {"instPart": self._installer_code})
        self._installer_open = True

    async def close(self) -> None:
        """Turn installer mode off again if this instance turned it on."""
        if not self._installer_open:
            return
        self._installer_open = False
        await self._client.get("/user-menu.html")

    async def _installer_get(self, path: str) -> str:
        await self.open_installer()
        return await self._client.get(path)

    # ─── reads ───────────────────────────────────────────────────

    async def fetch_dashboard(self) -> Dashboard:
        """Read outdoor temperature, operating mode and energy level."""
        return parse_dashboard(await self._client.get("/"))

    async def fetch_room_list(self) -> list[RoomListEntry]:
        """Read the zones and their names."""
        return parse_room_list(await self._client.get("/room-page.html"))

    async def fetch_room(self, zone: int) -> RoomDetail:
        """Read one room's temperatures, mode and capabilities."""
        return parse_room_detail(
            await self._client.post_key("/room-operating.html", str(zone))
        )

    async def fetch_room_setup(self, zone: int) -> RoomSetup:
        """Read one room's set-up form (flags, slots, program assignment)."""
        return parse_room_setup(
            await self._client.post_key("/room-set-up.html", str(zone))
        )

    async def fetch_messages(self) -> list[AlarmMessage]:
        """Read the alarm log."""
        return parse_messages(await self._client.get("/messages.html"))

    async def fetch_system_info(self) -> SystemInfo:
        """Read unique code, firmware versions and season window.

        Raises RehauInvalidDeviceError when the page has no unique code,
        i.e. the host is not a Nea Smart 2.0 base station.
        """
        info = parse_system_info(await self._client.get("/user-config-installer.html"))
        if not info.unique_code:
            raise RehauInvalidDeviceError(
                "no unique code on /user-config-installer.html"
            )
        return info

    async def fetch_daily_program(self, program_id: int) -> DailyProgram:
        """Read daily program 1..10; a page for another program is rejected."""
        _check_id("daily program", program_id, DAILY_PROGRAMS)
        program = parse_daily_program(
            await self._client.post_key(
                "/user-update-daily-program.html", str(program_id)
            )
        )
        if program.id != program_id:
            raise RehauInvalidDeviceError(
                f"asked for daily program {program_id}, got {program.id}"
            )
        return program

    async def fetch_weekly_program(self, program_id: int) -> WeeklyProgram:
        """Read weekly program 1..5; a page for another program is rejected."""
        _check_id("weekly program", program_id, WEEKLY_PROGRAMS)
        program = parse_weekly_program(
            await self._client.post_key(
                "/user-update-weekly-program.html", str(program_id)
            )
        )
        if program.id != program_id:
            raise RehauInvalidDeviceError(
                f"asked for weekly program {program_id}, got {program.id}"
            )
        return program

    async def fetch_calibration(self) -> Calibration:
        """Read the probe offsets (installer)."""
        return parse_calibration(await self._installer_get(_CALIBRATION_PAGE))

    async def fetch_io(self) -> IOSnapshot:
        """Read relays, digital and analog inputs (installer)."""
        return parse_io(await self._installer_get("/installer-inputoutput.html"))

    async def fetch_uptime(self) -> Uptime:
        """Read the controller uptime (installer)."""
        return parse_uptime(
            await self._installer_get("/installer-system-statistics.html")
        )

    async def fetch_topology(self) -> Topology:
        """Read the bus topology (installer)."""
        return parse_topology(await self._installer_get("/diagSett.html"))

    async def fetch_settings(self, group: InstallerSettingsGroup) -> InstallerSettings:
        """Read one installer settings page (installer)."""
        return settings_from_form(group, await self._settings_form(group))

    async def _settings_form(self, group: InstallerSettingsGroup) -> DeviceForm:
        html = await self._installer_get(SETTINGS_PAGES[group])
        return parse_form(html, SETTINGS_ACTION)

    # ─── writes ──────────────────────────────────────────────────

    async def write_room(
        self,
        zone: int,
        name: str,
        *,
        mode: RoomMode,
        setpoint: float,
        light: bool,
    ) -> None:
        """Post a room's mode, setpoint and light in one form.

        The form always carries `lightH`; leaving it out toggles the light,
        so callers pass the current light state when not changing it.
        """
        await self._client.post_form(
            "/room-page.html",
            {
                "zone": str(zone),
                "RoomName": name,
                **setpoint_to_form(setpoint, mode),
                "mode": room_mode_to_form(mode),
                "lightH": "1" if light else "0",
            },
        )

    async def write_room_flags(
        self,
        zone: int,
        *,
        lock: bool | None = None,
        auto_start: bool | None = None,
        window_detection: bool | None = None,
    ) -> None:
        """Change display lock, adaptive start or open-window detection.

        The set-up form is all-or-nothing, so it is read, changed and
        submitted in full, with the °F×10 hiddens its own script fills.
        """
        requested = {
            "lock": lock,
            "auto_start": auto_start,
            "window_detection": window_detection,
        }
        changes: dict[str, float | int | bool | str] = {
            _ROOM_SETUP_FLAGS[key]: value
            for key, value in requested.items()
            if value is not None
        }
        if not changes:
            return
        html = await self._client.post_key("/room-set-up.html", str(zone))
        form = parse_form(html, "room-page.html")
        if form.get("user-set-up") is None or form.get("zone") is None:
            raise RehauInvalidDeviceError(f"zone {zone} returned no room set-up form")
        changed = apply_changes(form, changes)
        await self._client.post_form(
            f"/{changed.action}", form_body(changed, fahrenheit_hidden=True)
        )

    async def set_operating_mode(self, mode: OperatingMode) -> None:
        """Set the system operating mode (season)."""
        await self._client.post_form(
            "/user-menu.html",
            {"operatingMode": "", "opMode": str(operating_mode_to_device(mode))},
        )

    async def set_energy_level(self, level: EnergyLevel) -> None:
        """Set the system energy level."""
        await self._client.post_form(
            "/user-menu.html",
            {"energyLevel": "", "energyL": str(energy_level_to_device(level))},
        )

    async def clear_messages(self) -> None:
        """Acknowledge every alarm, as the messages page's Confirm button does."""
        await self._client.post_form("/user-menu.html", {"MessagesHidden": ""})

    async def set_daily_program(self, program_id: int, bits: Sequence[int]) -> None:
        """Replace daily program 1..10 with 96 quarter-hour bits."""
        _check_id("daily program", program_id, DAILY_PROGRAMS)
        if len(bits) != QUARTERS_PER_DAY or any(bit not in (0, 1) for bit in bits):
            raise ValueError(f"a daily program needs {QUARTERS_PER_DAY} bits of 0 or 1")
        await self._client.post_form(
            "/user-daily-program.html",
            {
                "pDaily": "",
                "idProgDay": str(program_id - 1),
                "prog": "".join(str(bit) for bit in bits),
            },
        )

    async def set_weekly_program(self, program_id: int, days: Sequence[int]) -> None:
        """Assign daily programs (1..10) to Mon..Sun of weekly program 1..5."""
        _check_id("weekly program", program_id, WEEKLY_PROGRAMS)
        if len(days) != DAYS_PER_WEEK:
            raise ValueError(f"a weekly program needs {DAYS_PER_WEEK} days")
        for day in days:
            _check_id("daily program", day, DAILY_PROGRAMS)
        form = {"pWeek": "", "weeklyProgram": str(program_id)}
        form |= {f"PDay{index}": str(day - 1) for index, day in enumerate(days)}
        await self._client.post_form("/user-weekly-program.html", form)

    async def set_calibration(
        self,
        *,
        outdoor_offset: float | None = None,
        temperature_offsets: dict[int, float] | None = None,
        humidity_offsets: dict[int, float] | None = None,
    ) -> None:
        """Change probe offsets (installer); untouched offsets are resubmitted as read."""
        changes: dict[str, float | int | bool | str] = {}
        if outdoor_offset is not None:
            changes["out00"] = outdoor_offset
        for zone, offset in (temperature_offsets or {}).items():
            changes[f"air{zone:02d}"] = offset
        for zone, offset in (humidity_offsets or {}).items():
            changes[f"humi{zone:02d}"] = offset
        if not changes:
            return
        form = parse_form(
            await self._installer_get(_CALIBRATION_PAGE), _CALIBRATION_ACTION
        )
        changed = apply_changes(form, changes)
        await self._client.post_form(f"/{changed.action}", form_body(changed))

    async def set_settings(
        self, group: InstallerSettingsGroup, changes: dict[str, float | bool]
    ) -> None:
        """Change fields of one installer settings page; the rest are resubmitted as read."""
        if not changes:
            return
        form = await self._settings_form(group)
        changed = apply_changes(form, dict(changes))
        await self._client.post_form(f"/{changed.action}", form_body(changed))
