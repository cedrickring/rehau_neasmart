"""Codec tests, ported from the bridge's codecs.test.ts."""

import pytest

from custom_components.rehau_neasmart.api.codecs import (
    bits_to_intervals,
    celsius_to_f10,
    energy_level_from_device,
    energy_level_to_device,
    hhmm_to_quarter,
    intervals_to_bits,
    operating_mode_from_device,
    operating_mode_to_device,
    quantize_setpoint,
    quarter_to_hhmm,
    room_mode_from_device,
    room_mode_to_form,
    setpoint_to_form,
)
from custom_components.rehau_neasmart.api.models import (
    EnergyLevel,
    OperatingMode,
    RoomMode,
)


def test_quantizes_to_half_degree() -> None:
    assert quantize_setpoint(20.24) == 20.0
    assert quantize_setpoint(20.25) == 20.5
    assert quantize_setpoint(21) == 21.0


def test_quantize_rounds_half_up_like_javascript() -> None:
    # Python's round() would give 20.0 here (half-to-even).
    assert quantize_setpoint(20.25) == 20.5
    assert quantize_setpoint(20.75) == 21.0


@pytest.mark.parametrize(
    ("celsius", "rsh", "temp"),
    [(20, "20.0", "680"), (21, "21.0", "698"), (21.5, "21.5", "707")],
)
def test_encodes_setpoint_as_rsh_and_f10(celsius: float, rsh: str, temp: str) -> None:
    assert setpoint_to_form(celsius, RoomMode.NORMAL) == {"RSH": rsh, "temp": temp}


def test_encodes_standby_as_literal_a() -> None:
    assert setpoint_to_form(20, RoomMode.STANDBY) == {"RSH": "a", "temp": "0"}


def test_f10_rounds_inside_the_multiplication() -> None:
    # round((21.0 * 9/5 + 32) * 10) = round(698.0); rounding before ×10 gives 700.
    assert celsius_to_f10(21.0) == 698


def test_decodes_device_initial_state() -> None:
    assert room_mode_from_device(0) is RoomMode.NORMAL
    assert room_mode_from_device(1) is RoomMode.REDUCED
    assert room_mode_from_device(2) is RoomMode.STANDBY
    assert room_mode_from_device(3) is RoomMode.PROGRAM
    assert room_mode_from_device(4) is RoomMode.PROGRAM
    assert room_mode_from_device(5) is RoomMode.PROGRAM_OVERRIDE
    assert room_mode_from_device(6) is RoomMode.PROGRAM_OVERRIDE
    assert room_mode_from_device(7) is RoomMode.PROGRAM_OVERRIDE
    assert room_mode_from_device(42) is RoomMode.STANDBY


def test_encodes_room_mode_for_form() -> None:
    assert room_mode_to_form(RoomMode.PROGRAM_OVERRIDE) == "programO"
    assert room_mode_to_form(RoomMode.NORMAL) == "normal"


@pytest.mark.parametrize("mode", list(OperatingMode))
def test_operating_mode_round_trips(mode: OperatingMode) -> None:
    assert operating_mode_from_device(operating_mode_to_device(mode)) is mode


def test_unknown_operating_mode_reads_as_manual_heating() -> None:
    assert operating_mode_from_device(9) is OperatingMode.MANUAL_HEATING


def test_decodes_energy_level() -> None:
    assert energy_level_from_device(2) is EnergyLevel.STANDBY
    assert energy_level_from_device(4) is EnergyLevel.VACATION
    assert energy_level_from_device(99) is EnergyLevel.STANDBY


@pytest.mark.parametrize("level", list(EnergyLevel))
def test_energy_level_round_trips(level: EnergyLevel) -> None:
    assert energy_level_from_device(energy_level_to_device(level)) is level


def test_quarter_and_hhmm() -> None:
    assert quarter_to_hhmm(0) == "00:00"
    assert quarter_to_hhmm(24) == "06:00"
    assert quarter_to_hhmm(94) == "23:30"
    assert quarter_to_hhmm(96) == "24:00"
    assert hhmm_to_quarter("06:00") == 24
    assert hhmm_to_quarter("24:00") == 96


@pytest.mark.parametrize("text", ["06:10", "25:00", "24:15", "6", ""])
def test_rejects_bad_times(text: str) -> None:
    with pytest.raises(ValueError):
        hhmm_to_quarter(text)


def test_decodes_morning_and_evening_pattern() -> None:
    bits = [0] * 96
    for index in range(24, 36):
        bits[index] = 1
    for index in range(68, 92):
        bits[index] = 1
    assert bits_to_intervals(bits) == [("06:00", "09:00"), ("17:00", "23:00")]


def test_intervals_round_trip() -> None:
    intervals = [("06:00", "09:00"), ("17:00", "23:00")]
    assert bits_to_intervals(intervals_to_bits(intervals)) == intervals


def test_full_day_run() -> None:
    assert bits_to_intervals([1] * 96) == [("00:00", "24:00")]


def test_rejects_bad_bit_length() -> None:
    with pytest.raises(ValueError):
        bits_to_intervals([1, 0, 1])


def test_rejects_empty_interval() -> None:
    with pytest.raises(ValueError):
        intervals_to_bits([("10:00", "10:00")])
