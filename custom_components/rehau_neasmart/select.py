"""Selects: system operating mode and energy level."""

from __future__ import annotations

from typing import override

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .api.models import EnergyLevel, OperatingMode
from .coordinator import RehauCoordinator
from .entity import RehauEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the system selects."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [RehauOperatingModeSelect(coordinator), RehauEnergyLevelSelect(coordinator)]
    )


class RehauOperatingModeSelect(RehauEntity, SelectEntity):
    """The system operating mode; only the modes the device offers are listed."""

    _attr_translation_key = "operating_mode"

    def __init__(self, coordinator: RehauCoordinator) -> None:
        """Create the select."""
        super().__init__(coordinator, "operating_mode")

    @property
    @override
    def options(self) -> list[str]:
        """Return the modes the device offers (two on heating-only systems)."""
        dashboard = self.coordinator.state.dashboard
        if dashboard is None or not dashboard.operating_modes:
            return [mode.value for mode in OperatingMode]
        return [mode.value for mode in dashboard.operating_modes]

    @property
    @override
    def current_option(self) -> str | None:
        """Return the current mode."""
        dashboard = self.coordinator.state.dashboard
        return None if dashboard is None else dashboard.operating_mode.value

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the operating mode."""
        await self.coordinator.async_set_operating_mode(OperatingMode(option))


class RehauEnergyLevelSelect(RehauEntity, SelectEntity):
    """The system energy level."""

    _attr_translation_key = "energy_level"
    _attr_options = [level.value for level in EnergyLevel]

    def __init__(self, coordinator: RehauCoordinator) -> None:
        """Create the select."""
        super().__init__(coordinator, "energy_level")

    @property
    @override
    def current_option(self) -> str | None:
        """Return the current level."""
        dashboard = self.coordinator.state.dashboard
        return None if dashboard is None else dashboard.energy_level.value

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the energy level."""
        await self.coordinator.async_set_energy_level(EnergyLevel(option))
