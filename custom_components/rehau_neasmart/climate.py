"""Climate entity per room.

HVAC modes follow the system season: Off/Heat while heating, Off/Cool
while cooling, because a room cannot pick its season itself. The REHAU
room modes (normal, reduced, program, program override, standby) are the
presets.
"""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .api.models import RoomMode
from .const import (
    COOLING_MAX_TEMP,
    COOLING_MIN_TEMP,
    HEATING_MAX_TEMP,
    HEATING_MIN_TEMP,
    TEMPERATURE_STEP,
)
from .coordinator import RehauCoordinator
from .entity import RehauRoomEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one climate entity per room."""

    def build(coordinator: RehauCoordinator) -> list[RehauClimate]:
        return [RehauClimate(coordinator, zone) for zone in coordinator.state.rooms]

    async_add_dynamic_entities(
        entry, entry.runtime_data.coordinator, async_add_entities, build
    )


class RehauClimate(RehauRoomEntity, ClimateEntity):
    """A room thermostat."""

    _attr_name = None
    _attr_translation_key = "room"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMPERATURE_STEP
    _attr_preset_modes = [mode.value for mode in RoomMode]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: RehauCoordinator, zone: int) -> None:
        """Create the thermostat of a zone."""
        super().__init__(coordinator, zone, "climate")

    @property
    def _active_mode(self) -> HVACMode:
        return HVACMode.COOL if self.coordinator.state.is_cooling else HVACMode.HEAT

    @property
    @override
    def hvac_modes(self) -> list[HVACMode]:
        """Return Off plus the season's mode."""
        return [HVACMode.OFF, self._active_mode]

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return Off in standby, otherwise the season's mode."""
        if (room := self.room) is None:
            return None
        return HVACMode.OFF if room.mode is RoomMode.STANDBY else self._active_mode

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the REHAU room mode."""
        return room.mode.value if (room := self.room) else None

    @property
    @override
    def native_current_temperature(self) -> float | None:
        """Return the room temperature."""
        return room.temperature if (room := self.room) else None

    @property
    @override
    def current_humidity(self) -> float | None:
        """Return the room humidity, if the room has a probe."""
        return room.humidity if (room := self.room) else None

    @property
    @override
    def native_target_temperature(self) -> float | None:
        """Return the setpoint of the slot in use; standby shows the normal slot."""
        return room.active_setpoint if (room := self.room) else None

    @property
    @override
    def min_temp(self) -> float:
        """Return the lowest setpoint the device accepts this season."""
        if not self.coordinator.state.is_cooling:
            return HEATING_MIN_TEMP
        setup = self.coordinator.state.setups.get(self.zone)
        if setup is not None and setup.setpoints.min_cooling is not None:
            return setup.setpoints.min_cooling
        return COOLING_MIN_TEMP

    @property
    @override
    def max_temp(self) -> float:
        """Return the highest setpoint the device accepts this season."""
        if self.coordinator.state.is_cooling:
            return COOLING_MAX_TEMP
        setup = self.coordinator.state.setups.get(self.zone)
        if setup is not None and setup.setpoints.max_heating is not None:
            return setup.setpoints.max_heating
        return HEATING_MAX_TEMP

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature, switching HVAC mode first if asked to."""
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_set_room_setpoint(self.zone, temperature)

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Off is standby; Heat/Cool turns a standby room to normal and leaves others."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_room_mode(self.zone, RoomMode.STANDBY)
        elif self.hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_room_mode(self.zone, RoomMode.NORMAL)

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the REHAU room mode."""
        await self.coordinator.async_set_room_mode(self.zone, RoomMode(preset_mode))

    @override
    async def async_turn_on(self) -> None:
        """Turn a standby room to normal."""
        await self.async_set_hvac_mode(self._active_mode)

    @override
    async def async_turn_off(self) -> None:
        """Put the room in standby."""
        await self.async_set_hvac_mode(HVACMode.OFF)
