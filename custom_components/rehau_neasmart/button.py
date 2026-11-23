"""Button: acknowledge all alarms."""

from __future__ import annotations

from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .coordinator import RehauCoordinator
from .entity import RehauEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the acknowledge button."""
    async_add_entities([RehauClearMessagesButton(entry.runtime_data.coordinator)])


class RehauClearMessagesButton(RehauEntity, ButtonEntity):
    """Acknowledges every alarm, like the Confirm button on the messages page."""

    _attr_translation_key = "clear_messages"

    def __init__(self, coordinator: RehauCoordinator) -> None:
        """Create the button."""
        super().__init__(coordinator, "clear_messages")

    @override
    async def async_press(self) -> None:
        """Acknowledge the alarms."""
        await self.coordinator.async_clear_messages()
