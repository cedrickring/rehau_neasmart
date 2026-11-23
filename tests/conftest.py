"""Fixtures for the integration tests: a config entry and the German fw-6.15 house."""

from collections.abc import Generator
from unittest.mock import patch

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.rehau_neasmart.const import (
    CONF_EXPOSE_CALIBRATION,
    CONF_EXPOSE_IO,
    CONF_INSTALLER_CODE,
    DOMAIN,
)
from custom_components.rehau_neasmart.helpers import entry_unique_id

from .api.fake_client import FakeClient, german_device_client

FIXTURE_CODE = "aabbccdd00112233445566778899aabb"
UNIQUE_ID = entry_unique_id(FIXTURE_CODE)
HOST = "192.168.0.2"
INSTALLER_CODE = "abcd1234"


@pytest.fixture
def fake_client() -> FakeClient:
    """Serve the German capture of the five-room heating-only house."""
    return german_device_client()


@pytest.fixture
def mock_client(fake_client: FakeClient) -> Generator[FakeClient]:
    """Make the integration and the config flow talk to the fake client."""
    with (
        patch("custom_components.rehau_neasmart.RehauClient", return_value=fake_client),
        patch(
            "custom_components.rehau_neasmart.config_flow.RehauClient",
            return_value=fake_client,
        ),
        patch("custom_components.rehau_neasmart.coordinator.ROOM_LIST_RETRY_DELAY", 0),
    ):
        yield fake_client


@pytest.fixture
def options() -> dict[str, bool]:
    """Options of the config entry; installer entities on."""
    return {CONF_EXPOSE_IO: True, CONF_EXPOSE_CALIBRATION: True}


@pytest.fixture
def config_entry(options: dict[str, bool]) -> MockConfigEntry:
    """A config entry with an installer code."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="REHAU Nea Smart 2.0",
        unique_id=UNIQUE_ID,
        data={CONF_HOST: HOST, CONF_INSTALLER_CODE: INSTALLER_CODE},
        options=options,
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """A loaded config entry."""
    await setup_entry(hass, config_entry)
    return config_entry
