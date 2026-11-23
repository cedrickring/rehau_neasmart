"""Actions: programs, messages, installer settings."""

from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.rehau_neasmart.const import DOMAIN

from .api.fake_client import FakeClient
from .conftest import UNIQUE_ID, setup_entry


def posts(client: FakeClient) -> list[tuple[str, dict[str, str]]]:
    return [(path, body) for method, path, body in client.calls if method == "POST"]  # type: ignore[misc]


async def call(
    hass: HomeAssistant, service: str, data: dict, *, response: bool = False
) -> dict | None:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )


async def test_get_programs(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    result = await call(
        hass,
        "get_programs",
        {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id},
        response=True,
    )
    assert result is not None
    assert [program["program"] for program in result["daily"]] == list(range(1, 11))
    assert sum(len(program["periods"]) for program in result["daily"]) > 0
    assert result["weekly"][4] == {
        "program": 5,
        "monday": 9,
        "tuesday": 9,
        "wednesday": 9,
        "thursday": 9,
        "friday": 3,
        "saturday": 2,
        "sunday": 2,
    }


async def test_set_daily_program(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "set_daily_program",
        {
            ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id,
            "program": 4,
            "periods": [
                {"start": "06:00", "end": "08:30"},
                {"start": "18:00", "end": "24:00"},
            ],
        },
    )
    path, body = posts(mock_client)[0]
    assert path == "/user-daily-program.html"
    assert body["idProgDay"] == "3"
    assert body["prog"] == "0" * 24 + "1" * 10 + "0" * 38 + "1" * 24
    assert mock_client.calls[-1] == ("KEY", "/user-update-daily-program.html", "4")


async def test_set_daily_program_rejects_bad_period(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    with pytest.raises(ServiceValidationError):
        await call(
            hass,
            "set_daily_program",
            {
                ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id,
                "program": 1,
                "periods": [{"start": "06:10", "end": "08:00"}],
            },
        )
    assert posts(mock_client) == []


async def test_set_weekly_program_keeps_other_days(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "set_weekly_program",
        {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id, "program": 5, "friday": 9},
    )
    body = posts(mock_client)[0][1]
    assert [body[f"PDay{day}"] for day in range(7)] == [
        "8",
        "8",
        "8",
        "8",
        "8",
        "1",
        "1",
    ]


async def test_set_weekly_program_unknown_needs_all_days(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    loaded_entry.runtime_data.coordinator.state.weekly_programs.pop(2)
    with pytest.raises(ServiceValidationError):
        await call(
            hass,
            "set_weekly_program",
            {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id, "program": 2, "monday": 1},
        )


async def test_get_messages(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    result = await call(
        hass,
        "get_messages",
        {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id},
        response=True,
    )
    assert result is not None
    assert len(result["messages"]) == 20
    first = result["messages"][0]
    assert set(first) == {
        "index",
        "severity",
        "source",
        "code",
        "started_at",
        "resolved_at",
        "active",
    }


async def test_get_installer_settings(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    result = await call(
        hass,
        "get_installer_settings",
        {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id, "group": "heatcool"},
        response=True,
    )
    assert result is not None
    assert result["fields"]["HG1"] == {
        "value": 15.0,
        "min": 5.0,
        "max": 25.0,
        "step": 0.1,
    }


async def test_set_installer_settings(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    await call(
        hass,
        "set_installer_settings",
        {
            ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id,
            "group": "heatcool",
            "values": {"HG1": 15.5},
        },
    )
    path, body = posts(mock_client)[0]
    assert path == "/installer-setting.html"
    assert body["HG1"] == "15.5"
    assert body["heatcoolSett"] == ""
    assert mock_client.calls[-1] == ("GET", "/hCSett.html", None)


async def test_set_installer_settings_out_of_range(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.calls.clear()
    with pytest.raises(ServiceValidationError, match="maximum"):
        await call(
            hass,
            "set_installer_settings",
            {
                ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id,
                "group": "heatcool",
                "values": {"HG1": 30},
            },
        )
    assert [path for path, _ in posts(mock_client)] == []


async def test_installer_actions_need_a_code(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=UNIQUE_ID, data={"host": "192.168.0.2"}, options={}
    )
    await setup_entry(hass, entry)
    with pytest.raises(ServiceValidationError):
        await call(
            hass,
            "get_installer_settings",
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id, "group": "pid"},
            response=True,
        )


async def test_action_on_unloaded_entry(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    await hass.config_entries.async_unload(loaded_entry.entry_id)
    with pytest.raises(HomeAssistantError):
        await call(
            hass,
            "get_programs",
            {ATTR_CONFIG_ENTRY_ID: loaded_entry.entry_id},
            response=True,
        )
