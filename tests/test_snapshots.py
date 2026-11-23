"""Entity registry entries and states per platform, against the German capture."""

from unittest.mock import patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .api.fake_client import FakeClient
from .conftest import setup_entry


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    "platform",
    [
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.CLIMATE,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    ],
)
async def test_platform(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    mock_client: FakeClient,
    config_entry: MockConfigEntry,
    platform: Platform,
) -> None:
    with patch("custom_components.rehau_neasmart.PLATFORMS", [platform]):
        await setup_entry(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)
