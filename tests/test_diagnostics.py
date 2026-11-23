"""Diagnostics never contain the installer code or the device's unique code."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator

from .conftest import FIXTURE_CODE, INSTALLER_CODE, UNIQUE_ID


async def test_diagnostics_are_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    loaded_entry: MockConfigEntry,
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, loaded_entry)
    text = str(result)
    assert INSTALLER_CODE not in text
    assert FIXTURE_CODE not in text
    assert UNIQUE_ID not in text
    assert result["installer_open"] is True
    assert result["state"]["system"]["firmware"]["master"] == "6.15"
    assert len(result["state"]["rooms"]) == 5
    # The fake client bypasses RehauClient, so no requests are logged here.
    assert result["recent_requests"] == []
    assert result["io"]["master"]["relay"] == [1.0, 0.0, 0.0, 0.0]
