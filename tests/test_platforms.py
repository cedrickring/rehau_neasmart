"""Writes through the entities and what they post to the device."""

from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.rehau_neasmart.const import CONF_EXPOSE_IO, DOMAIN

from .api.fake_client import FakeClient
from .conftest import setup_entry

BATHROOM = "climate.rehau_nea_smart_2_0_bathroom"
PREFIX = "rehau_nea_smart_2_0"


def posts(client: FakeClient) -> list[tuple[str, dict[str, str]]]:
    return [(path, body) for method, path, body in client.calls if method == "POST"]  # type: ignore[misc]


def standby_page(client: FakeClient, zone: int) -> None:
    key = f"/room-operating.html#{zone}"
    client.pages[key] = client.pages[key].replace("initialState =0", "initialState =2")


async def call(hass: HomeAssistant, domain: str, service: str, data: dict) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)


async def test_climate_state(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    state = hass.states.get(BATHROOM)
    assert state.state == HVACMode.HEAT
    assert state.attributes["hvac_modes"] == [HVACMode.OFF, HVACMode.HEAT]
    assert state.attributes["current_temperature"] == 23.7
    assert state.attributes["temperature"] == 22.0
    assert state.attributes["preset_mode"] == "normal"
    assert state.attributes["min_temp"] == 5
    # The room's own heating limit from its set-up form, not the 31 °C default.
    assert state.attributes["max_temp"] == 26
    assert "current_humidity" not in state.attributes


async def test_set_temperature(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "climate",
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: BATHROOM, ATTR_TEMPERATURE: 23.5},
    )
    assert posts(mock_client) == [
        (
            "/room-page.html",
            {
                "zone": "0",
                "RoomName": "Bathroom",
                "RSH": "23.5",
                "temp": "743",
                "mode": "normal",
                "lightH": "0",
            },
        )
    ]
    # The room is re-read right after the write.
    assert mock_client.calls[-1] == ("KEY", "/room-operating.html", "0")


async def test_set_temperature_with_hvac_mode(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "climate",
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: BATHROOM, ATTR_TEMPERATURE: 21, ATTR_HVAC_MODE: HVACMode.OFF},
    )
    assert [body["mode"] for _, body in posts(mock_client)] == ["standby", "normal"]


async def test_turn_off_sends_standby(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(hass, "climate", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: BATHROOM})
    body = posts(mock_client)[0][1]
    assert (body["mode"], body["RSH"]) == ("standby", "a")


async def test_heat_on_a_running_room_writes_nothing(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "climate",
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: BATHROOM, ATTR_HVAC_MODE: HVACMode.HEAT},
    )
    assert posts(mock_client) == []


async def test_turn_on_a_standby_room_sends_normal_slot(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    standby_page(mock_client, 0)
    await setup_entry(hass, config_entry)
    assert hass.states.get(BATHROOM).state == HVACMode.OFF
    mock_client.calls.clear()
    await call(hass, "climate", SERVICE_TURN_ON, {ATTR_ENTITY_ID: BATHROOM})
    body = posts(mock_client)[0][1]
    assert (body["mode"], body["RSH"]) == ("normal", "22.0")


async def test_preset_sends_the_target_modes_slot(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "climate",
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: BATHROOM, ATTR_PRESET_MODE: "reduced"},
    )
    await call(
        hass,
        "climate",
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: BATHROOM, ATTR_PRESET_MODE: "program_override"},
    )
    (_, reduced), (_, override) = posts(mock_client)
    assert (reduced["mode"], reduced["RSH"]) == ("reduced", "19.0")
    assert (override["mode"], override["RSH"]) == ("programO", "22.0")


async def test_failed_write_raises(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.fail_paths.add("/room-page.html")
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await call(
            hass,
            "climate",
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: BATHROOM, ATTR_TEMPERATURE: 22},
        )


async def test_light_switch_resends_mode_and_setpoint(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: f"switch.{PREFIX}_office_light"},
    )
    body = posts(mock_client)[0][1]
    assert body == {
        "zone": "4",
        "RoomName": "Office",
        "RSH": "23.0",
        "temp": "734",
        "mode": "normal",
        "lightH": "1",
    }


@pytest.mark.parametrize(
    ("entity", "service", "flag", "present"),
    [
        ("display_lock", SERVICE_TURN_ON, "Lock", True),
        ("open_window_detection", SERVICE_TURN_OFF, "SWOW", False),
        ("adaptive_start", SERVICE_TURN_OFF, "Auto", False),
    ],
)
async def test_flag_switches_round_trip_the_setup_form(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
    entity: str,
    service: str,
    flag: str,
    present: bool,
) -> None:
    mock_client.calls.clear()
    await call(
        hass, "switch", service, {ATTR_ENTITY_ID: f"switch.{PREFIX}_hallway_{entity}"}
    )
    path, body = posts(mock_client)[0]
    assert path == "/room-page.html"
    assert body["zone"] == "3"
    assert (flag in body) is present
    assert mock_client.calls[-1] == ("KEY", "/room-set-up.html", "3")


async def test_flag_switch_state(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert hass.states.get(f"switch.{PREFIX}_hallway_display_lock").state == "off"
    assert (
        hass.states.get(f"switch.{PREFIX}_hallway_open_window_detection").state == "on"
    )


async def test_operating_mode_select_offers_only_device_modes(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    entity = f"select.{PREFIX}_operating_mode"
    state = hass.states.get(entity)
    assert state.state == "manual_heating"
    assert state.attributes["options"] == ["manual_heating", "heating_only"]
    mock_client.calls.clear()
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity, ATTR_OPTION: "heating_only"},
    )
    assert posts(mock_client) == [
        ("/user-menu.html", {"operatingMode": "", "opMode": "1"})
    ]
    assert ("GET", "/", None) in mock_client.calls


async def test_energy_level_select(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: f"select.{PREFIX}_energy_level", ATTR_OPTION: "vacation"},
    )
    assert posts(mock_client) == [
        ("/user-menu.html", {"energyLevel": "", "energyL": "4"})
    ]


async def test_acknowledge_button(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "button",
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: f"button.{PREFIX}_acknowledge_alarms"},
    )
    assert posts(mock_client) == [("/user-menu.html", {"MessagesHidden": ""})]
    assert ("GET", "/messages.html", None) in mock_client.calls


async def test_calibration_number(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    entity = f"number.{PREFIX}_office_temperature_offset"
    state = hass.states.get(entity)
    assert state.state == "0.0"
    assert (
        state.attributes["min"],
        state.attributes["max"],
        state.attributes["step"],
    ) == (-5, 5, 0.1)
    mock_client.calls.clear()
    await call(
        hass, "number", SERVICE_SET_VALUE, {ATTR_ENTITY_ID: entity, ATTR_VALUE: -0.7}
    )
    path, body = posts(mock_client)[0]
    assert path == "/installer-diagnosis.html"
    assert body["air04"] == "-0.7"
    assert body["air00"] == "0.0"


async def test_calibration_number_rejects_off_step_value(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    coordinator = loaded_entry.runtime_data.coordinator
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_calibration(temperature_offsets={4: 0.05})


async def test_alarm_sensors(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    active = sum(
        message.active
        for message in loaded_entry.runtime_data.coordinator.state.messages
    )
    assert hass.states.get(f"sensor.{PREFIX}_active_alarms").state == str(active)
    assert hass.states.get(f"binary_sensor.{PREFIX}_alarms").state == (
        "on" if active else "off"
    )


async def test_no_outdoor_or_humidity_sensor_without_probes(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert hass.states.get(f"sensor.{PREFIX}_outdoor_temperature") is None
    assert hass.states.get(f"sensor.{PREFIX}_bathroom_humidity") is None


async def test_io_entities_are_disabled_by_default(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    io = [
        entry
        for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        if "_io_" in (entry.unique_id or "")
    ]
    assert len(io) == 16  # 8 zone valves, 4 relays, 4 digital inputs on the master
    assert all(entry.disabled_by is not None for entry in io)


async def test_io_off_option_skips_io_polling(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=config_entry.unique_id,
        data=config_entry.data,
        options={CONF_EXPOSE_IO: False},
    )
    await setup_entry(hass, config_entry)
    assert config_entry.runtime_data.io_coordinator is None
    assert "/installer-inputoutput.html" not in [
        path for _, path, _ in mock_client.calls
    ]


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_house_with_fancoil_humidity_outdoor_and_umodule(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    pages = mock_client.pages
    pages["/"] = pages["/"].replace(
        '<h2 class="textCenter">',
        '<h3 class="textCenter">Außentemp. -3.5</h3><h2 class="textCenter">',
    )
    pages["/room-operating.html#0"] = (
        pages["/room-operating.html#0"]
        .replace(
            '<br><div class="textCenter">',
            '<span class="spanHum"><label class="labelLeft">Feuchte</label>'
            '<label class="labelRight greyR">48 %</label></span><svg id="FFF"></svg>'
            '<br><div class="textCenter">',
            1,
        )
        .replace(
            "var initialFan =1;",
            'var initialFan =2;document.getElementById("FFF").style.fill="#DD0060";',
        )
    )
    mock_client.serve(
        "/installer-inputoutput.html", "synthetic/installer-inputoutput.html"
    )
    await setup_entry(hass, config_entry)

    assert hass.states.get(f"sensor.{PREFIX}_outdoor_temperature").state == "-3.5"
    assert hass.states.get(f"sensor.{PREFIX}_bathroom_humidity").state == "48.0"
    assert hass.states.get(BATHROOM).attributes["current_humidity"] == 48
    assert hass.states.get(f"sensor.{PREFIX}_bathroom_fancoil_speed").state == "medium"
    assert hass.states.get(f"binary_sensor.{PREFIX}_bathroom_fancoil").state == "on"
    assert hass.states.get(f"binary_sensor.{PREFIX}_bathroom_flap").state == "off"
    assert hass.states.get("sensor.u_module_0_analog_input_1").state == "22.6"
    assert hass.states.get("sensor.u_module_0_analog_input_3").state == "unknown"
    assert hass.states.get("sensor.u_module_0_analog_output").state == "35.0"
    assert hass.states.get("binary_sensor.u_module_0_relay_1").state == "on"
