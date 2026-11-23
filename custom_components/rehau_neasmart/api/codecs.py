"""Encoding between REHAU device values and the typed models.

Every device quirk about numbers and enums lives here.
"""

from __future__ import annotations

import math
import re

from .models import EnergyLevel, OperatingMode, RoomMode

QUARTERS_PER_DAY = 96


def _js_round(value: float) -> int:
    """Round half up like JavaScript's Math.round (Python's round() is half-even)."""
    return math.floor(value + 0.5)


def quantize_setpoint(celsius: float) -> float:
    """Quantize a temperature to the device's 0.5 °C step."""
    return _js_round(celsius * 2) / 2


def celsius_to_f10(celsius: float) -> int:
    """Encode °C as the device's integer °F×10.

    The ×10 sits inside the rounding, as in the device's own JavaScript;
    rounding first drifts by ~0.1 °C on a round trip.
    """
    return _js_round((celsius * 9 / 5 + 32) * 10)


def setpoint_to_form(celsius: float, mode: RoomMode) -> dict[str, str]:
    """Encode a setpoint the way the device UI posts it: `RSH` in °C and `temp` in °F×10.

    Standby is posted as the literal `RSH=a`.
    """
    if mode is RoomMode.STANDBY:
        return {"RSH": "a", "temp": "0"}
    quantized = quantize_setpoint(celsius)
    return {"RSH": f"{quantized:.1f}", "temp": str(celsius_to_f10(quantized))}


_DEVICE_STATE_TO_ROOM_MODE = {
    0: RoomMode.NORMAL,
    1: RoomMode.REDUCED,
    2: RoomMode.STANDBY,
    3: RoomMode.PROGRAM,  # program, day view
    4: RoomMode.PROGRAM,  # program, current slot
    5: RoomMode.PROGRAM_OVERRIDE,
    6: RoomMode.PROGRAM_OVERRIDE,  # party
    7: RoomMode.PROGRAM_OVERRIDE,  # forced
}

_ROOM_MODE_TO_FORM = {
    RoomMode.NORMAL: "normal",
    RoomMode.REDUCED: "reduced",
    RoomMode.STANDBY: "standby",
    RoomMode.PROGRAM: "program",
    RoomMode.PROGRAM_OVERRIDE: "programO",
}

_OPERATING_MODE_CODES = {
    OperatingMode.HEATING_ONLY: 1,
    OperatingMode.COOLING_ONLY: 2,
    OperatingMode.MANUAL_HEATING: 5,
    OperatingMode.MANUAL_COOLING: 6,
}

_ENERGY_LEVEL_CODES = {
    EnergyLevel.NORMAL: 0,
    EnergyLevel.REDUCED: 1,
    EnergyLevel.STANDBY: 2,
    EnergyLevel.AUTO: 3,
    EnergyLevel.VACATION: 4,
}


def room_mode_from_device(state: int) -> RoomMode:
    """Decode the `initialState` JS variable (0..7); unknown values read as standby."""
    return _DEVICE_STATE_TO_ROOM_MODE.get(state, RoomMode.STANDBY)


def room_mode_to_form(mode: RoomMode) -> str:
    """Encode a room mode as the `mode` field of a room-page.html POST."""
    return _ROOM_MODE_TO_FORM[mode]


def operating_mode_from_device(code: int) -> OperatingMode:
    """Decode the `opMode` select; unknown codes read as manual heating."""
    for mode, value in _OPERATING_MODE_CODES.items():
        if value == code:
            return mode
    return OperatingMode.MANUAL_HEATING


def operating_mode_to_device(mode: OperatingMode) -> int:
    """Encode an operating mode for the `opMode` field."""
    return _OPERATING_MODE_CODES[mode]


def energy_level_from_device(code: int) -> EnergyLevel:
    """Decode the `energyL` select; unknown codes read as standby."""
    for level, value in _ENERGY_LEVEL_CODES.items():
        if value == code:
            return level
    return EnergyLevel.STANDBY


def energy_level_to_device(level: EnergyLevel) -> int:
    """Encode an energy level for the `energyL` field."""
    return _ENERGY_LEVEL_CODES[level]


_HHMM = re.compile(r"^([01]?\d|2[0-4]):([0-5]\d)$")


def quarter_to_hhmm(quarter: int) -> str:
    """Render a quarter-hour index (0..96) as HH:MM; 96 is 24:00."""
    return f"{quarter // 4:02d}:{quarter % 4 * 15:02d}"


def hhmm_to_quarter(text: str) -> int:
    """Parse HH:MM on a 15-minute boundary into a quarter-hour index (0..96)."""
    match = _HHMM.match(text)
    if match is None:
        raise ValueError(f"bad time: {text}")
    hours, minutes = int(match[1]), int(match[2])
    if minutes % 15:
        raise ValueError(f"time must be on a 15-minute boundary: {text}")
    quarter = hours * 4 + minutes // 15
    if quarter > QUARTERS_PER_DAY:
        raise ValueError(f"time is past 24:00: {text}")
    return quarter


def bits_to_intervals(bits: tuple[int, ...] | list[int]) -> list[tuple[str, str]]:
    """Collapse 96 quarter-hour bits into (start, end) HH:MM runs of ones."""
    if len(bits) != QUARTERS_PER_DAY:
        raise ValueError(f"bits must be length {QUARTERS_PER_DAY}, got {len(bits)}")
    out: list[tuple[str, str]] = []
    run_start: int | None = None
    for index, bit in enumerate(bits):
        if bit and run_start is None:
            run_start = index
        elif not bit and run_start is not None:
            out.append((quarter_to_hhmm(run_start), quarter_to_hhmm(index)))
            run_start = None
    if run_start is not None:
        out.append((quarter_to_hhmm(run_start), quarter_to_hhmm(QUARTERS_PER_DAY)))
    return out


def intervals_to_bits(intervals: list[tuple[str, str]]) -> tuple[int, ...]:
    """Expand (start, end) HH:MM runs into 96 quarter-hour bits."""
    bits = [0] * QUARTERS_PER_DAY
    for start, end in intervals:
        first, last = hhmm_to_quarter(start), hhmm_to_quarter(end)
        if last <= first:
            raise ValueError(f"interval end must be after start: {start}..{end}")
        for index in range(first, last):
            bits[index] = 1
    return tuple(bits)
