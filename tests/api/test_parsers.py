"""Parser tests: the bridge's parsers.test.ts cases plus the pages it never tested.

`fw-6.15/` fixtures come from the bridge repo. `synthetic/` fixtures are
hand-written from the bridge's selectors until real captures replace them.
"""

from datetime import datetime

import pytest
from pytest_homeassistant.common import load_fixture

from custom_components.rehau_neasmart.api.models import (
    AlarmSeverity,
    EnergyLevel,
    OperatingMode,
    RoomMode,
)
from custom_components.rehau_neasmart.api.parsers import (
    parse_calibration,
    parse_daily_program,
    parse_dashboard,
    parse_heat_curve,
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


def fw(name: str) -> str:
    return load_fixture(f"fw-6.15/{name}")


def synthetic(name: str) -> str:
    return load_fixture(f"synthetic/{name}")


def test_dashboard() -> None:
    dashboard = parse_dashboard(fw("dashboard.html"))
    assert dashboard.outdoor_temperature == 19.0
    assert dashboard.clock == "2026-05-18 14:32"
    assert dashboard.operating_mode is OperatingMode.MANUAL_HEATING
    assert dashboard.energy_level is EnergyLevel.STANDBY


def test_dashboard_without_outdoor_heading_is_unknown_not_zero() -> None:
    dashboard = parse_dashboard("<html><body></body></html>")
    assert dashboard.outdoor_temperature is None
    assert dashboard.operating_mode is OperatingMode.MANUAL_HEATING
    assert dashboard.energy_level is EnergyLevel.STANDBY


def test_room_list() -> None:
    rooms = parse_room_list(fw("room-page.html"))
    assert [(r.zone, r.name, r.temperature) for r in rooms] == [
        (0, "Arianna", 22.5),
        (1, "Manu", 23.8),
        (2, "Cucina", 24.7),
        (3, "Salone", 21.7),
    ]


def test_room_list_empty_page() -> None:
    assert parse_room_list("<html></html>") == []


def test_room_detail_zone_0_standby() -> None:
    room = parse_room_detail(fw("room-operating-0.html"))
    assert room.zone == 0
    assert room.name == "Arianna"
    assert room.temperature == 22.5
    assert room.humidity == 47
    assert room.setpoint == 20.0
    assert room.setpoint_normal == 20.0
    assert room.setpoint_reduced == 18.5
    assert room.setpoint_standby == 23.0
    assert room.mode is RoomMode.STANDBY
    assert room.fan == 1
    assert room.has_light is False


def test_room_detail_zone_3_program_with_light() -> None:
    room = parse_room_detail(fw("room-operating-3.html"))
    assert room.zone == 3
    assert room.name == "Salone"
    assert room.mode is RoomMode.PROGRAM
    assert room.program_active == 0
    assert room.light is False
    assert room.has_light is True
    assert room.active_setpoint == 20.0


def test_room_detail_fan_running_marker() -> None:
    html = fw("room-operating-0.html").replace(
        "</body>",
        '<svg id="FFF"></svg><script>document.getElementById("FFF").style.fill="#DD0060";</script></body>',
    )
    room = parse_room_detail(html)
    assert room.has_fan is True
    assert room.has_flap is True
    assert room.fan_running is True


@pytest.mark.parametrize(
    ("mode_state", "program_active", "expected"),
    [(0, 0, 20.0), (1, 0, 18.5), (2, 0, 20.0), (3, 1, 18.5), (5, 0, 20.0)],
)
def test_active_setpoint_follows_mode(
    mode_state: int, program_active: int, expected: float
) -> None:
    html = (
        fw("room-operating-3.html")
        .replace("initialState=3", f"initialState={mode_state}")
        .replace("programActual=0", f"programActual={program_active}")
    )
    assert parse_room_detail(html).active_setpoint == expected


def test_room_setup() -> None:
    setup = parse_room_setup(synthetic("room-set-up.html"))
    assert setup.zone == 2
    assert setup.name == "Cucina"
    assert setup.setpoints.normal_heating == 20.5
    assert setup.setpoints.reduced_heating == 18.5
    assert setup.setpoints.standby == 10.0
    assert setup.setpoints.normal_cooling == 26.0
    assert setup.setpoints.reduced_cooling == 28.0
    assert setup.setpoints.max_heating == 31.0
    assert setup.setpoints.min_cooling == 15.0
    assert setup.auto_start is True
    assert setup.window_detection is False
    assert setup.lock is True
    assert setup.weekly_program == 2
    assert setup.day_programs == (1, 1, 1, 1, 1, 2, 2)


def test_messages() -> None:
    messages = parse_messages(fw("messages.html"))
    assert len(messages) == 4
    assert messages[0].severity is AlarmSeverity.WARNING
    assert messages[0].source == "MC 1"
    assert messages[0].code == "2/02/06/06/01/051/3"
    assert messages[0].started_at == datetime(2026, 3, 31, 11, 28)  # noqa: DTZ001
    assert messages[0].resolved_at == datetime(2026, 3, 31, 11, 51)  # noqa: DTZ001
    assert messages[3].severity is AlarmSeverity.ERROR
    assert messages[3].source == "Base"
    assert messages[3].code == "4/00/00/01/00/200/3"
    assert not any(message.active for message in messages)


def test_message_without_end_is_active() -> None:
    html = fw("messages.html").replace(
        '<td class="cell5">2026/3/31 11:51</td>', '<td class="cell5">-</td>'
    )
    assert parse_messages(html)[0].active is True


def test_daily_program() -> None:
    bits = "0" * 24 + "1" * 12 + "0" * 32 + "1" * 24 + "0" * 4
    html = f"""<html><body><form action="user-daily-program.html" method="post">
      <input name="pDaily" type="hidden">
      <input name="idProgDay" type="hidden" value="0" id="hidden">
      <input id="prog" name="prog" type="hidden" value="{bits}">
    </form></body></html>"""
    program = parse_daily_program(html)
    assert program.id == 1
    assert len(program.bits) == 96
    assert all(program.bits[24:36])
    assert not any(program.bits[:24])


def test_daily_program_short_string_pads_with_zeros() -> None:
    html = '<input name="idProgDay" value="4"><input name="prog" value="111">'
    program = parse_daily_program(html)
    assert program.id == 5
    assert program.bits[:4] == (1, 1, 1, 0)
    assert len(program.bits) == 96


def test_weekly_program() -> None:
    selects = "".join(
        f'<select name="PDay{day}">'
        + "".join(
            f'<option value="{value}"{" selected" if value == chosen else ""}>{value + 1}</option>'
            for value in range(3)
        )
        + "</select>"
        for day, chosen in enumerate([0, 0, 0, 0, 0, 1, 1])
    )
    html = f"""<html><body><form action="user-weekly-program.html" method="post">
      <input name="pWeek" type="hidden">
      <input name="weeklyProgram" type="hidden" value="2" id="hidden">{selects}
    </form></body></html>"""
    program = parse_weekly_program(html)
    assert program.id == 2
    assert program.days == (1, 1, 1, 1, 1, 2, 2)


def _uptime_page(line: str) -> str:
    return f"<html><body><h1>System statistics</h1><p>{line}</p></body></html>"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Controller running : 0 Year(s) 0 Day(s) 3 Hour(s)", (0, 0, 3)),
        ("Sistema operativo da: 0 Anno 14 Giorno 6 Ora", (0, 14, 6)),
        ("Steuerung läuft seit: 1 Jahr(e) 3 Tag(e) 12 Stunde(n)", (1, 3, 12)),
        ("Nothing here", (0, 0, 0)),
    ],
)
def test_uptime_in_any_language(line: str, expected: tuple[int, int, int]) -> None:
    uptime = parse_uptime(_uptime_page(line))
    assert (uptime.years, uptime.days, uptime.hours) == expected


def test_system_info() -> None:
    info = parse_system_info(fw("user-config-installer.html"))
    assert info.unique_code == "aabbccdd00112233445566778899aabbccddeeff00112233"
    assert info.firmware.master == "6.15"
    assert info.firmware.web == "0.25"
    assert info.firmware.umodules == {0: "1.2"}
    assert info.season_start == "10-01"
    assert info.season_end == "05-01"
    assert info.outdoor_offset == 0


def test_system_info_in_english() -> None:
    html = (
        fw("user-config-installer.html")
        .replace("Versione pagina Web 0.25", "Web page version 0.25")
        .replace("Versione Modulo-U 0: 1.2", "U-Module 0 version: 1. 2")
    )
    info = parse_system_info(html)
    assert info.firmware.web == "0.25"
    assert info.firmware.umodules == {0: "1.2"}


def test_calibration() -> None:
    calibration = parse_calibration(synthetic("installer-adjustementOffset.html"))
    assert calibration.outdoor_offset == -0.5
    assert sorted(calibration.rooms) == [0, 1, 2]
    assert calibration.rooms[0].temperature_offset == 0.3
    assert calibration.rooms[0].humidity_offset == -2
    assert calibration.rooms[2].temperature_offset == -1.0


def test_io() -> None:
    io = parse_io(synthetic("installer-inputoutput.html"))
    assert io.master.rz == (1, 0, 0, 1, 0, 0, 0, 0)
    assert io.master.relay == (0, 1, 0, 0)
    assert io.master.di == (0, 0, 0, 1)
    assert list(io.umodules) == [0]
    module = io.umodules[0]
    assert module.relay == (1, 0, 0, 0)
    assert module.ai == (22.6, 21.9, None, None)
    assert module.ao == 35


def test_io_with_english_module_heading() -> None:
    io = parse_io(
        synthetic("installer-inputoutput.html").replace("Modulo-U 0", "U-Module 1")
    )
    assert list(io.umodules) == [1]


def test_topology() -> None:
    topology = parse_topology(synthetic("diagSett.html"))
    assert topology.base_modules == 1
    assert topology.u_modules == 1
    assert topology.rooms == 5
    assert topology.mixed_circuits == 1


def test_heat_curve() -> None:
    curve = parse_heat_curve(synthetic("circSett.html"))
    assert curve.slope_normal == 0.6
    assert curve.start_normal == 20
    assert curve.max_flow_absent == 35
