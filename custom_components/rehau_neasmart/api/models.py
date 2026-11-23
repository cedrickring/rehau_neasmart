"""Typed snapshots of what the REHAU Nea Smart 2.0 web UI shows.

Zones are the device's own 0-based indices everywhere in this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RoomMode(StrEnum):
    """Per-room operating mode."""

    NORMAL = "normal"
    REDUCED = "reduced"
    STANDBY = "standby"
    PROGRAM = "program"
    PROGRAM_OVERRIDE = "program_override"


class OperatingMode(StrEnum):
    """System-wide operating mode (season)."""

    HEATING_ONLY = "heating_only"
    COOLING_ONLY = "cooling_only"
    MANUAL_HEATING = "manual_heating"
    MANUAL_COOLING = "manual_cooling"

    @property
    def is_cooling(self) -> bool:
        """Return True for the two cooling modes."""
        return self in (OperatingMode.COOLING_ONLY, OperatingMode.MANUAL_COOLING)


class EnergyLevel(StrEnum):
    """System-wide energy level."""

    NORMAL = "normal"
    REDUCED = "reduced"
    STANDBY = "standby"
    AUTO = "auto"
    VACATION = "vacation"


class AlarmSeverity(StrEnum):
    """Severity letter of a messages.html row."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InstallerSettingsGroup(StrEnum):
    """Installer settings pages handled by the generic settings module."""

    CURVE = "curve"
    HEATCOOL = "heatcool"
    DEVICES = "devices"
    FUNCTIONS = "functions"
    PID = "pid"
    FANCOIL = "fancoil"


@dataclass(frozen=True, slots=True)
class Dashboard:
    """The resident dashboard at `/`."""

    outdoor_temperature: float | None
    clock: str
    operating_mode: OperatingMode
    energy_level: EnergyLevel


@dataclass(frozen=True, slots=True)
class RoomListEntry:
    """One button on `/room-page.html`."""

    zone: int
    name: str
    temperature: float | None


@dataclass(frozen=True, slots=True)
class RoomDetail:
    """The per-room page `/room-operating.html`."""

    zone: int
    name: str
    temperature: float | None
    humidity: float | None
    setpoint: float | None
    setpoint_normal: float | None
    setpoint_reduced: float | None
    setpoint_standby: float | None
    mode: RoomMode
    program_active: int
    fan: int
    flap: int
    light: bool
    has_light: bool
    has_fan: bool
    has_flap: bool
    fan_running: bool

    @property
    def active_setpoint(self) -> float | None:
        """Return the setpoint slot that drives the room in its current mode.

        In program modes `programActual` says which slot the program is on:
        1 means reduced, anything else normal.
        """
        match self.mode:
            case RoomMode.REDUCED:
                return self.setpoint_reduced
            case RoomMode.PROGRAM | RoomMode.PROGRAM_OVERRIDE if (
                self.program_active == 1
            ):
                return self.setpoint_reduced
            case _:
                return self.setpoint_normal


@dataclass(frozen=True, slots=True)
class RoomSetpoints:
    """Setpoint slots on `/room-set-up.html`, all in °C."""

    normal_heating: float
    reduced_heating: float
    standby: float
    normal_cooling: float
    reduced_cooling: float
    max_heating: float
    min_cooling: float


@dataclass(frozen=True, slots=True)
class RoomSetup:
    """The all-or-nothing form on `/room-set-up.html`."""

    zone: int
    name: str
    setpoints: RoomSetpoints
    auto_start: bool
    window_detection: bool
    lock: bool
    weekly_program: int
    """0 = none, 1..5 = weekly slot."""
    day_programs: tuple[int, ...]
    """Mon..Sun daily slot, 1..10."""


@dataclass(frozen=True, slots=True)
class AlarmMessage:
    """One row of `/messages.html`."""

    index: int
    severity: AlarmSeverity
    source: str
    code: str
    started_at: datetime | None
    resolved_at: datetime | None

    @property
    def active(self) -> bool:
        """Return True while the alarm has no end timestamp."""
        return self.resolved_at is None


@dataclass(frozen=True, slots=True)
class FirmwareInfo:
    """Firmware versions on `/user-config-installer.html`."""

    master: str
    web: str
    umodules: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SystemInfo:
    """`/user-config-installer.html`."""

    unique_code: str
    firmware: FirmwareInfo
    season_start: str
    season_end: str
    outdoor_offset: float


@dataclass(frozen=True, slots=True)
class DailyProgram:
    """A daily program: 96 quarter-hour bits from 00:00 to 24:00."""

    id: int
    bits: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WeeklyProgram:
    """A weekly program: daily slot (1..10) for Mon..Sun."""

    id: int
    days: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RoomCalibration:
    """Installer probe offsets of one room."""

    zone: int
    temperature_offset: float
    humidity_offset: float


@dataclass(frozen=True, slots=True)
class Calibration:
    """`/installer-adjustementOffset.html`."""

    outdoor_offset: float
    rooms: dict[int, RoomCalibration]


@dataclass(frozen=True, slots=True)
class Uptime:
    """Controller uptime from `/installer-system-statistics.html`."""

    years: int
    days: int
    hours: int


@dataclass(frozen=True, slots=True)
class Topology:
    """Bus topology from `/diagSett.html`."""

    base_modules: int
    r_modules: int
    u_modules: int
    rooms: int
    mixed_circuits: int
    dehumidifiers: int


@dataclass(frozen=True, slots=True)
class HeatCurve:
    """Heating curve fields from `/circSett.html`."""

    slope_normal: float
    slope_absent: float
    start_normal: float
    start_absent: float
    reduction_k: float
    min_flow_normal: float
    min_flow_absent: float
    max_flow_normal: float
    max_flow_absent: float


@dataclass(frozen=True, slots=True)
class MasterIO:
    """Base-station channels on `/installer-inputoutput.html`."""

    rz: tuple[float, ...]
    relay: tuple[float, ...]
    di: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class UModuleIO:
    """One U-module's channels on `/installer-inputoutput.html`."""

    relay: tuple[float, ...]
    di: tuple[float, ...]
    ai: tuple[float | None, ...]
    ao: float


@dataclass(frozen=True, slots=True)
class IOSnapshot:
    """`/installer-inputoutput.html`."""

    master: MasterIO
    umodules: dict[int, UModuleIO]


@dataclass(frozen=True, slots=True)
class InstallerSettings:
    """All fields of one installer settings page, keyed by input name."""

    group: InstallerSettingsGroup
    values: dict[str, float | bool]
