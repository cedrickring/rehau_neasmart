"""Polling and writes for one base station.

The device serves one request at a time, so everything goes through one
RehauClient and the polling cadence follows rehau-bridge (core/poller.ts):

- every tick: each room's detail page; the tick length is
  clamp(5 s × rooms, 10 s, 30 s);
- dashboard and room list every 120 s, messages every 300 s, system info
  every 600 s;
- every 1800 s (and on the first refresh): room set-ups, programs and the
  installer pages, so edits made on the device itself are picked up;
- I/O every 10 s in its own coordinator, when enabled.

Each fetched piece lands in the shared state as soon as it arrives. Since
the client runs requests strictly in order, the latest arrival is always
the latest reading, including the re-read after a write.

Writes are optimistic, as in rehau-bridge: the expected state is shown at
once, then the device is written and re-read. Losing one packet on the
Wi-Fi link costs about 2 s (the base station's retransmission timeout), so
waiting for the device made switches feel laggy. While a write is pending,
polls drop their results for the same room, set-up or dashboard, so a read
that was already in flight cannot flip the state back.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
import time
from typing import TYPE_CHECKING, Any, override

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryError,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import FetchRecord
from .api.device import DAILY_PROGRAMS, WEEKLY_PROGRAMS, RehauDevice
from .api.exceptions import RehauError
from .api.models import (
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
    RoomMode,
    RoomSetup,
    SystemInfo,
    Topology,
    Uptime,
    WeeklyProgram,
)
from .const import (
    DASHBOARD_INTERVAL,
    DOMAIN,
    FULL_SYNC_INTERVAL,
    IO_INTERVAL,
    LOGGER,
    MESSAGES_INTERVAL,
    ROOM_CYCLE_MAX,
    ROOM_CYCLE_MIN,
    ROOM_LIST_INTERVAL,
    ROOM_LIST_RETRY_DELAY,
    ROOM_SECONDS_PER_ZONE,
    SYSTEM_INFO_INTERVAL,
)
from .helpers import entry_unique_id

if TYPE_CHECKING:
    from . import RehauConfigEntry


# Pending-write key of the dashboard (operating mode, energy level).
DASHBOARD_KEY = ("dashboard", 0)


def room_cycle(rooms: int) -> timedelta:
    """Return the tick length for this many rooms."""
    seconds = timedelta(seconds=ROOM_SECONDS_PER_ZONE * max(1, rooms))
    return min(ROOM_CYCLE_MAX, max(ROOM_CYCLE_MIN, seconds))


def setpoint_changes(room: RoomDetail, value: float) -> dict[str, float]:
    """Return the slot a setpoint write lands in, mirroring `active_setpoint`.

    In standby the device ignores the setpoint, so nothing changes.
    """
    match room.mode:
        case RoomMode.STANDBY:
            return {}
        case RoomMode.REDUCED:
            return {"setpoint_reduced": value}
        case RoomMode.PROGRAM | RoomMode.PROGRAM_OVERRIDE if room.program_active == 1:
            return {"setpoint_reduced": value}
        case _:
            return {"setpoint_normal": value}


def setpoint_for_mode(room: RoomDetail, mode: RoomMode) -> float | None:
    """Return the stored slot to send when switching a room to `mode`.

    Writing the current setpoint instead would file e.g. the normal value
    into the reduced slot. Program modes start from the normal slot.
    """
    match mode:
        case RoomMode.REDUCED:
            return room.setpoint_reduced
        case RoomMode.STANDBY:
            return room.setpoint_standby
        case _:
            return room.setpoint_normal


@dataclass
class RehauState:
    """Everything read from the device so far."""

    system: SystemInfo
    dashboard: Dashboard | None = None
    room_names: dict[int, str] = field(default_factory=dict)
    rooms: dict[int, RoomDetail] = field(default_factory=dict)
    setups: dict[int, RoomSetup] = field(default_factory=dict)
    messages: list[AlarmMessage] | None = None
    daily_programs: dict[int, DailyProgram] = field(default_factory=dict)
    weekly_programs: dict[int, WeeklyProgram] = field(default_factory=dict)
    calibration: Calibration | None = None
    uptime: Uptime | None = None
    topology: Topology | None = None
    settings: dict[InstallerSettingsGroup, InstallerSettings] = field(
        default_factory=dict
    )

    @property
    def is_cooling(self) -> bool:
        """Return True while the system runs in a cooling mode."""
        return self.dashboard is not None and self.dashboard.operating_mode.is_cooling


class RehauCoordinator(DataUpdateCoordinator[RehauState]):
    """Polls the base station and performs writes."""

    config_entry: RehauConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: RehauConfigEntry,
        device: RehauDevice,
        fetches: deque[FetchRecord],
    ) -> None:
        """Create the coordinator; the first refresh reads everything once."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=ROOM_CYCLE_MIN,
        )
        self.device = device
        self.fetches = fetches
        self._state: RehauState | None = None
        self._last_success: dict[str, float] = {}
        self._errors: list[str] = []
        self._booted = False
        self._pending: Counter[tuple[str, int]] = Counter()

    @property
    def state(self) -> RehauState:
        """Return the shared state; only valid after the first refresh."""
        if self._state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_ready"
            )
        return self._state

    @override
    async def _async_setup(self) -> None:
        """Identify the device and refuse a different one at the same address."""
        try:
            system = await self.device.fetch_system_info()
        except RehauError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if entry_unique_id(system.unique_code) != self.config_entry.unique_id:
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="wrong_device"
            )
        self._state = RehauState(system=system)
        self._last_success["system_info"] = time.monotonic()

    def _due(self, task: str, interval: timedelta) -> bool:
        last = self._last_success.get(task)
        return last is None or time.monotonic() - last >= interval.total_seconds()

    async def _step(self, task: str, fetch: Callable[[], Awaitable[None]]) -> bool:
        """Run one fetch; a failure is logged and leaves the old value in place."""
        try:
            await fetch()
        except RehauError as err:
            LOGGER.debug("Fetching %s failed: %s", task, err)
            self._errors.append(f"{task}: {err}")
            return False
        self._last_success[task] = time.monotonic()
        return True

    @override
    async def _async_update_data(self) -> RehauState:
        state = self.state
        self._errors = []
        ok = 0

        if self._due("dashboard", DASHBOARD_INTERVAL):
            ok += await self._step(
                "dashboard", lambda: self.refresh_dashboard(poll=True)
            )
        if self._due("room_list", ROOM_LIST_INTERVAL):
            ok += await self._step("room_list", self._refresh_room_list)
            if not self._booted and not state.room_names:
                LOGGER.debug("Room list empty at start, retrying once")
                await asyncio.sleep(ROOM_LIST_RETRY_DELAY)
                ok += await self._step("room_list", self._refresh_room_list)
        for zone in list(state.room_names):
            ok += await self._step(
                f"room_{zone}", lambda z=zone: self.refresh_room(z, poll=True)
            )
        if self._due("system_info", SYSTEM_INFO_INTERVAL):
            ok += await self._step("system_info", self._refresh_system_info)
        if self._due("messages", MESSAGES_INTERVAL):
            ok += await self._step("messages", self.refresh_messages)
        if self._due("full_sync", FULL_SYNC_INTERVAL):
            ok += await self._full_sync()

        if not ok:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": "; ".join(self._errors)},
            )
        if not state.room_names:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="no_rooms")
        self._booted = True
        self.update_interval = room_cycle(len(state.room_names))
        return state

    async def _full_sync(self) -> int:
        """Read the pages that change rarely; succeeds when any of them did."""
        state = self.state
        ok = 0
        for zone in list(state.room_names):
            ok += await self._step(
                f"setup_{zone}", lambda z=zone: self.refresh_setup(z, poll=True)
            )
        for program in range(1, DAILY_PROGRAMS + 1):
            ok += await self._step(
                f"daily_{program}", lambda p=program: self.refresh_daily_program(p)
            )
        for program in range(1, WEEKLY_PROGRAMS + 1):
            ok += await self._step(
                f"weekly_{program}", lambda p=program: self.refresh_weekly_program(p)
            )
        if self.device.has_installer:
            ok += await self._step("calibration", self.refresh_calibration)
            ok += await self._step("uptime", self._refresh_uptime)
            ok += await self._step("topology", self._refresh_topology)
            for group in InstallerSettingsGroup:
                ok += await self._step(
                    f"settings_{group}", lambda g=group: self.refresh_settings(g)
                )
        if ok:
            self._last_success["full_sync"] = time.monotonic()
        return ok

    # ─── single-page refreshes ───────────────────────────────────

    async def refresh_dashboard(self, *, poll: bool = False) -> None:
        """Re-read outdoor temperature, operating mode and energy level."""
        dashboard = await self.device.fetch_dashboard()
        if not (poll and self._pending[DASHBOARD_KEY]):
            self.state.dashboard = dashboard

    async def _refresh_room_list(self) -> None:
        rooms = await self.device.fetch_room_list()
        state = self.state
        state.room_names = {room.zone: room.name for room in rooms}
        for zone in set(state.rooms) - set(state.room_names):
            del state.rooms[zone]
            state.setups.pop(zone, None)

    async def refresh_room(self, zone: int, *, poll: bool = False) -> None:
        """Re-read one room's detail page."""
        room = await self.device.fetch_room(zone)
        if not (poll and self._pending[("room", zone)]):
            self.state.rooms[zone] = room

    async def refresh_setup(self, zone: int, *, poll: bool = False) -> None:
        """Re-read one room's set-up form."""
        setup = await self.device.fetch_room_setup(zone)
        if not (poll and self._pending[("setup", zone)]):
            self.state.setups[zone] = setup

    async def _refresh_system_info(self) -> None:
        self.state.system = await self.device.fetch_system_info()

    async def refresh_messages(self) -> None:
        """Re-read the alarm log."""
        self.state.messages = await self.device.fetch_messages()

    async def refresh_daily_program(self, program: int) -> None:
        """Re-read one daily program."""
        self.state.daily_programs[program] = await self.device.fetch_daily_program(
            program
        )

    async def refresh_weekly_program(self, program: int) -> None:
        """Re-read one weekly program."""
        self.state.weekly_programs[program] = await self.device.fetch_weekly_program(
            program
        )

    async def refresh_calibration(self) -> None:
        """Re-read the probe offsets."""
        self.state.calibration = await self.device.fetch_calibration()

    async def _refresh_uptime(self) -> None:
        self.state.uptime = await self.device.fetch_uptime()

    async def _refresh_topology(self) -> None:
        self.state.topology = await self.device.fetch_topology()

    async def refresh_settings(self, group: InstallerSettingsGroup) -> None:
        """Re-read one installer settings page."""
        self.state.settings[group] = await self.device.fetch_settings(group)

    # ─── writes ──────────────────────────────────────────────────

    def _patch_room(self, zone: int, **changes: Any) -> Callable[[], None]:
        rooms = self.state.rooms
        old = rooms[zone]
        new = rooms[zone] = replace(old, **changes)

        def revert() -> None:
            if rooms.get(zone) is new:
                rooms[zone] = old

        return revert

    def _patch_setup(self, zone: int, **changes: Any) -> Callable[[], None]:
        setups = self.state.setups
        if (old := setups.get(zone)) is None:
            return lambda: None
        new = setups[zone] = replace(old, **changes)

        def revert() -> None:
            if setups.get(zone) is new:
                setups[zone] = old

        return revert

    def _patch_dashboard(self, **changes: Any) -> Callable[[], None]:
        state = self.state
        if (old := state.dashboard) is None:
            return lambda: None
        new = state.dashboard = replace(old, **changes)

        def revert() -> None:
            if state.dashboard is new:
                state.dashboard = old

        return revert

    async def _write(
        self,
        write: Callable[[], Awaitable[None]],
        *refreshes: Callable[[], Awaitable[None]],
        pending: tuple[str, int] | None = None,
        patch: Callable[[], Callable[[], None]] | None = None,
    ) -> None:
        """Show the expected state, write, re-read what changed.

        `patch` applies the expected state and returns how to undo it; it is
        undone when the device refuses the write. A failed re-read after a
        successful write is left to the next poll.
        """
        if pending is not None:
            self._pending[pending] += 1
        try:
            revert = patch() if patch is not None else None
            if revert is not None:
                self.async_update_listeners()
            try:
                await write()
            except (RehauError, ValueError) as err:
                if revert is not None:
                    revert()
                if isinstance(err, ValueError):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="write_rejected",
                        translation_placeholders={"error": str(err)},
                    ) from err
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="write_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            for refresh in refreshes:
                try:
                    await refresh()
                except RehauError as err:
                    LOGGER.debug("Re-read after write failed: %s", err)
        finally:
            if pending is not None:
                self._pending[pending] -= 1
            self.async_update_listeners()

    def room(self, zone: int) -> RoomDetail:
        """Return a room's last reading, or raise if it was never read."""
        room = self.state.rooms.get(zone)
        if room is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="room_unknown",
                translation_placeholders={"zone": str(zone)},
            )
        return room

    async def async_set_room_setpoint(self, zone: int, value: float) -> None:
        """Set a room's target temperature in its current mode."""
        room = self.room(zone)
        await self._write(
            lambda: self.device.write_room(
                zone, room.name, mode=room.mode, setpoint=value, light=room.light
            ),
            lambda: self.refresh_room(zone),
            pending=("room", zone),
            patch=lambda: self._patch_room(zone, **setpoint_changes(room, value)),
        )

    async def async_set_room_mode(self, zone: int, mode: RoomMode) -> None:
        """Switch a room's mode, sending the stored setpoint of the target mode."""
        room = self.room(zone)
        setpoint = setpoint_for_mode(room, mode)
        if setpoint is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="setpoint_unknown"
            )
        await self._write(
            lambda: self.device.write_room(
                zone, room.name, mode=mode, setpoint=setpoint, light=room.light
            ),
            lambda: self.refresh_room(zone),
            pending=("room", zone),
            patch=lambda: self._patch_room(zone, mode=mode),
        )

    async def async_set_room_light(self, zone: int, light: bool) -> None:
        """Switch a room's light, resending its mode and setpoint unchanged."""
        room = self.room(zone)
        setpoint = room.active_setpoint
        if setpoint is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="setpoint_unknown"
            )
        await self._write(
            lambda: self.device.write_room(
                zone, room.name, mode=room.mode, setpoint=setpoint, light=light
            ),
            lambda: self.refresh_room(zone),
            pending=("room", zone),
            patch=lambda: self._patch_room(zone, light=light),
        )

    async def async_set_room_flags(
        self,
        zone: int,
        *,
        lock: bool | None = None,
        auto_start: bool | None = None,
        window_detection: bool | None = None,
    ) -> None:
        """Change a room's set-up flags."""
        self.room(zone)
        await self._write(
            lambda: self.device.write_room_flags(
                zone,
                lock=lock,
                auto_start=auto_start,
                window_detection=window_detection,
            ),
            lambda: self.refresh_setup(zone),
            pending=("setup", zone),
            patch=lambda: self._patch_setup(
                zone,
                **{
                    key: value
                    for key, value in (
                        ("lock", lock),
                        ("auto_start", auto_start),
                        ("window_detection", window_detection),
                    )
                    if value is not None
                },
            ),
        )

    async def async_set_operating_mode(self, mode: OperatingMode) -> None:
        """Set the system operating mode."""
        await self._write(
            lambda: self.device.set_operating_mode(mode),
            self.refresh_dashboard,
            pending=DASHBOARD_KEY,
            patch=lambda: self._patch_dashboard(operating_mode=mode),
        )

    async def async_set_energy_level(self, level: EnergyLevel) -> None:
        """Set the system energy level."""
        await self._write(
            lambda: self.device.set_energy_level(level),
            self.refresh_dashboard,
            pending=DASHBOARD_KEY,
            patch=lambda: self._patch_dashboard(energy_level=level),
        )

    async def async_clear_messages(self) -> None:
        """Acknowledge every alarm."""
        await self._write(self.device.clear_messages, self.refresh_messages)

    async def async_set_daily_program(
        self, program: int, bits: tuple[int, ...]
    ) -> None:
        """Replace a daily program."""
        await self._write(
            lambda: self.device.set_daily_program(program, bits),
            lambda: self.refresh_daily_program(program),
        )

    async def async_set_weekly_program(
        self, program: int, days: tuple[int, ...]
    ) -> None:
        """Replace a weekly program's day assignment."""
        await self._write(
            lambda: self.device.set_weekly_program(program, days),
            lambda: self.refresh_weekly_program(program),
        )

    async def async_set_calibration(
        self,
        *,
        outdoor_offset: float | None = None,
        temperature_offsets: dict[int, float] | None = None,
        humidity_offsets: dict[int, float] | None = None,
    ) -> None:
        """Change probe offsets."""
        await self._write(
            lambda: self.device.set_calibration(
                outdoor_offset=outdoor_offset,
                temperature_offsets=temperature_offsets,
                humidity_offsets=humidity_offsets,
            ),
            self.refresh_calibration,
        )

    async def async_set_settings(
        self, group: InstallerSettingsGroup, changes: dict[str, float | bool]
    ) -> None:
        """Change fields of an installer settings page."""
        await self._write(
            lambda: self.device.set_settings(group, changes),
            lambda: self.refresh_settings(group),
        )


class RehauIOCoordinator(DataUpdateCoordinator[IOSnapshot]):
    """Polls the installer I/O page."""

    config_entry: RehauConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: RehauConfigEntry, device: RehauDevice
    ) -> None:
        """Create the I/O coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_io",
            update_interval=IO_INTERVAL,
            always_update=False,
        )
        self.device = device

    @override
    async def _async_update_data(self) -> IOSnapshot:
        try:
            return await self.device.fetch_io()
        except RehauError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
