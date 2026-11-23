"""RehauDevice tests against the German fw-6.15 captures."""

import pytest

from custom_components.rehau_neasmart.api.device import RehauDevice
from custom_components.rehau_neasmart.api.exceptions import (
    RehauInstallerError,
    RehauInvalidDeviceError,
)
from custom_components.rehau_neasmart.api.models import (
    EnergyLevel,
    InstallerSettingsGroup,
    OperatingMode,
    RoomMode,
)

from .fake_client import FakeClient, german_device_client

CODE = "abcd1234"


@pytest.fixture
def client() -> FakeClient:
    return german_device_client()


@pytest.fixture
def device(client: FakeClient) -> RehauDevice:
    return RehauDevice(client, CODE)  # type: ignore[arg-type]


def posts(client: FakeClient) -> list[tuple[str, dict[str, str]]]:
    return [(path, body) for method, path, body in client.calls if method == "POST"]  # type: ignore[misc]


async def test_reads_the_real_dashboard(device: RehauDevice) -> None:
    dashboard = await device.fetch_dashboard()
    assert dashboard.outdoor_temperature is None
    assert dashboard.operating_mode is OperatingMode.MANUAL_HEATING
    assert dashboard.energy_level is EnergyLevel.NORMAL
    assert dashboard.operating_modes == (
        OperatingMode.MANUAL_HEATING,
        OperatingMode.HEATING_ONLY,
    )


async def test_reads_rooms_with_gap_in_zones(device: RehauDevice) -> None:
    rooms = await device.fetch_room_list()
    assert [(room.zone, room.name) for room in rooms] == [
        (0, "Bathroom"),
        (1, "Living Room"),
        (3, "Hallway"),
        (4, "Office"),
        (5, "Bedroom"),
    ]


async def test_reads_room_without_humidity_probe(device: RehauDevice) -> None:
    room = await device.fetch_room(0)
    assert room.name == "Bathroom"
    assert room.temperature == 23.7
    assert room.humidity is None
    assert room.mode is RoomMode.NORMAL
    assert room.setpoint_normal == 22.0
    assert room.setpoint_reduced == 19.0
    assert room.setpoint_standby == 15.0
    assert room.has_light is True
    assert room.has_fan is False


async def test_reads_heating_only_room_setup(device: RehauDevice) -> None:
    setup = await device.fetch_room_setup(1)
    assert setup.name == "Living Room"
    assert setup.setpoints.normal_heating == 22.5
    assert setup.setpoints.max_heating == 26.0
    assert setup.setpoints.normal_cooling is None
    assert setup.setpoints.min_cooling is None
    assert (setup.auto_start, setup.window_detection, setup.lock) == (True, True, False)
    assert setup.weekly_program == 1


async def test_system_info_code_stops_at_label_boundary(device: RehauDevice) -> None:
    info = await device.fetch_system_info()
    # The page is followed by a "6W" label; the code must not absorb its "6".
    assert info.unique_code == "aabbccdd00112233445566778899aabb"
    assert info.firmware.master == "6.15"
    assert info.firmware.web == "0.25"


async def test_system_info_without_code_is_not_a_rehau_device(
    device: RehauDevice, client: FakeClient
) -> None:
    client.pages["/user-config-installer.html"] = "<html><body>router</body></html>"
    with pytest.raises(RehauInvalidDeviceError):
        await device.fetch_system_info()


async def test_reads_messages(device: RehauDevice) -> None:
    messages = await device.fetch_messages()
    assert len(messages) == 20


async def test_reads_programs_by_one_based_id(
    device: RehauDevice, client: FakeClient
) -> None:
    daily = await device.fetch_daily_program(2)
    weekly = await device.fetch_weekly_program(5)
    assert daily.id == 2
    assert sum(daily.bits) == 68
    assert weekly.days == (9, 9, 9, 9, 3, 2, 2)
    assert ("KEY", "/user-update-daily-program.html", "2") in client.calls


@pytest.mark.parametrize("program_id", [0, 11])
async def test_rejects_daily_program_id_out_of_range(
    device: RehauDevice, program_id: int
) -> None:
    with pytest.raises(ValueError):
        await device.fetch_daily_program(program_id)


async def test_installer_read_logs_in_once(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.fetch_io()
    await device.fetch_uptime()
    assert posts(client) == [("/menu.html", {"instPart": CODE})]
    assert device.installer_open


async def test_close_logs_out(device: RehauDevice, client: FakeClient) -> None:
    await device.fetch_topology()
    await device.close()
    assert client.calls[-1] == ("GET", "/user-menu.html", None)
    assert not device.installer_open


async def test_close_without_login_sends_nothing(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.close()
    assert client.calls == []


async def test_installer_read_without_code_raises(client: FakeClient) -> None:
    device = RehauDevice(client, None)  # type: ignore[arg-type]
    assert not device.has_installer
    with pytest.raises(RehauInstallerError):
        await device.fetch_io()
    assert client.calls == []


async def test_reads_installer_pages(device: RehauDevice) -> None:
    calibration = await device.fetch_calibration()
    assert calibration.outdoor_offset is None
    assert sorted(calibration.rooms) == [0, 1, 3, 4, 5]
    assert calibration.rooms[0].humidity_offset is None
    io = await device.fetch_io()
    assert io.master.relay == (1, 0, 0, 0)
    assert io.umodules == {}
    uptime = await device.fetch_uptime()
    assert (uptime.years, uptime.days, uptime.hours) == (0, 76, 22)
    topology = await device.fetch_topology()
    assert (topology.rooms, topology.u_modules, topology.mixed_circuits) == (5, 0, 0)


async def test_settings_come_from_the_page_not_a_catalogue(device: RehauDevice) -> None:
    pid = await device.fetch_settings(InstallerSettingsGroup.PID)
    # Three PID blocks on this installation; the bridge only knew block 0.
    assert {"a0", "a1", "a2", "i2"} <= set(pid.fields)
    assert pid.fields["a0"].value == 4.0
    assert (pid.fields["a0"].minimum, pid.fields["a0"].maximum) == (0, 10)
    curve = await device.fetch_settings(InstallerSettingsGroup.CURVE)
    assert curve.fields == {}
    functions = await device.fetch_settings(InstallerSettingsGroup.FUNCTIONS)
    assert functions.fields["PU20"].value is True
    assert "PU25" not in functions.fields


async def test_write_room_posts_setpoint_mode_and_light(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.write_room(
        3, "Hallway", mode=RoomMode.NORMAL, setpoint=21.5, light=True
    )
    assert posts(client) == [
        (
            "/room-page.html",
            {
                "zone": "3",
                "RoomName": "Hallway",
                "RSH": "21.5",
                "temp": "707",
                "mode": "normal",
                "lightH": "1",
            },
        )
    ]


async def test_write_room_standby(device: RehauDevice, client: FakeClient) -> None:
    await device.write_room(
        0, "Bathroom", mode=RoomMode.STANDBY, setpoint=22, light=False
    )
    body = posts(client)[0][1]
    assert (body["RSH"], body["temp"], body["mode"], body["lightH"]) == (
        "a",
        "0",
        "standby",
        "0",
    )


async def test_write_room_flags_round_trips_the_real_form(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.write_room_flags(0, lock=True)
    path, body = posts(client)[0]
    assert path == "/room-page.html"
    assert body == {
        "user-set-up": "",
        "RoomName": "Bathroom",
        "zone": "0",
        "HNormH": "716",
        "HRedH": "662",
        "HStandH": "590",
        "PWeek": "1",
        "PDay00": "0",
        "PDay01": "0",
        "PDay02": "0",
        "PDay03": "0",
        "PDay04": "0",
        "PDay05": "0",
        "PDay06": "0",
        "Auto": "on",
        "SWOW": "on",
        "Lock": "on",
        "SPMaxH": "788",
    }


async def test_write_room_flags_can_clear_a_flag(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.write_room_flags(0, window_detection=False)
    body = posts(client)[0][1]
    assert "SWOW" not in body
    assert body["Auto"] == "on"
    assert "Lock" not in body


async def test_write_room_flags_without_changes_sends_nothing(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.write_room_flags(0)
    assert client.calls == []


async def test_write_room_flags_refuses_a_page_without_the_form(
    device: RehauDevice, client: FakeClient
) -> None:
    with pytest.raises(ValueError):
        # Zone 2 does not exist: the fake serves an empty page.
        await device.write_room_flags(2, lock=True)
    assert posts(client) == []


async def test_system_writes(device: RehauDevice, client: FakeClient) -> None:
    await device.set_operating_mode(OperatingMode.HEATING_ONLY)
    await device.set_energy_level(EnergyLevel.VACATION)
    await device.clear_messages()
    assert posts(client) == [
        ("/user-menu.html", {"operatingMode": "", "opMode": "1"}),
        ("/user-menu.html", {"energyLevel": "", "energyL": "4"}),
        ("/user-menu.html", {"MessagesHidden": ""}),
    ]


async def test_program_writes(device: RehauDevice, client: FakeClient) -> None:
    bits = [0] * 24 + [1] * 72
    await device.set_daily_program(3, bits)
    await device.set_weekly_program(2, [1, 1, 1, 1, 1, 2, 10])
    (daily_path, daily), (weekly_path, weekly) = posts(client)
    assert daily_path == "/user-daily-program.html"
    assert daily == {"pDaily": "", "idProgDay": "2", "prog": "0" * 24 + "1" * 72}
    assert weekly_path == "/user-weekly-program.html"
    assert weekly == {
        "pWeek": "",
        "weeklyProgram": "2",
        "PDay0": "0",
        "PDay1": "0",
        "PDay2": "0",
        "PDay3": "0",
        "PDay4": "0",
        "PDay5": "1",
        "PDay6": "9",
    }


@pytest.mark.parametrize(
    ("program_id", "bits"),
    [(3, [1] * 95), (3, [2] * 96), (0, [0] * 96), (11, [0] * 96)],
)
async def test_rejects_bad_daily_program(
    device: RehauDevice, client: FakeClient, program_id: int, bits: list[int]
) -> None:
    with pytest.raises(ValueError):
        await device.set_daily_program(program_id, bits)
    assert client.calls == []


@pytest.mark.parametrize("days", [[1] * 6, [1, 1, 1, 1, 1, 1, 11], [0] * 7])
async def test_rejects_bad_weekly_program(
    device: RehauDevice, client: FakeClient, days: list[int]
) -> None:
    with pytest.raises(ValueError):
        await device.set_weekly_program(1, days)
    assert client.calls == []


async def test_calibration_write_resubmits_only_existing_fields(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.set_calibration(temperature_offsets={3: -0.5})
    path, body = posts(client)[-1]
    assert path == "/installer-diagnosis.html"
    assert body == {
        "OffsetAdj": "",
        "air00": "0.0",
        "air01": "0.0",
        "air03": "-0.5",
        "air04": "0.0",
        "air05": "0.0",
    }


async def test_calibration_write_rejects_missing_humidity_probe(
    device: RehauDevice, client: FakeClient
) -> None:
    with pytest.raises(ValueError, match="humi00"):
        await device.set_calibration(humidity_offsets={0: 2})
    assert [path for path, _ in posts(client)] == ["/menu.html"]


async def test_settings_write_keeps_every_other_field(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.set_settings(InstallerSettingsGroup.PID, {"a1": 5.5})
    path, body = posts(client)[-1]
    assert path == "/installer-setting.html"
    assert body["AdvSett"] == ""
    assert body["a1"] == "5.5"
    assert body["a0"] == "4.0"
    assert {"a2", "b2", "i2"} <= set(body)


async def test_settings_write_validates_device_limits(
    device: RehauDevice, client: FakeClient
) -> None:
    with pytest.raises(ValueError, match="maximum"):
        await device.set_settings(InstallerSettingsGroup.PID, {"a0": 11})
    with pytest.raises(ValueError, match="multiple"):
        await device.set_settings(InstallerSettingsGroup.PID, {"c0": 25})
    with pytest.raises(ValueError, match="no field"):
        await device.set_settings(InstallerSettingsGroup.DEVICES, {"HE20": 50})
    assert [path for path, _ in posts(client)] == ["/menu.html"]


async def test_settings_write_toggles_checkbox(
    device: RehauDevice, client: FakeClient
) -> None:
    await device.set_settings(InstallerSettingsGroup.FUNCTIONS, {"PU20": False})
    body = posts(client)[-1][1]
    assert "PU20" not in body
    assert body["PU3"] == "on"
