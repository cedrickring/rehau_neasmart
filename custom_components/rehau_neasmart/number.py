"""Numbers: installer probe offsets (calibration), when enabled in the options."""

from __future__ import annotations

from typing import override

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .api.models import SettingValue
from .const import CONF_EXPOSE_CALIBRATION, DEFAULT_EXPOSE_CALIBRATION
from .coordinator import RehauCoordinator
from .entity import RehauEntity, RehauRoomEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add an offset per calibration row the device shows."""
    if not entry.runtime_data.device.has_installer or not entry.options.get(
        CONF_EXPOSE_CALIBRATION, DEFAULT_EXPOSE_CALIBRATION
    ):
        return

    def build(coordinator: RehauCoordinator) -> list[Entity]:
        calibration = coordinator.state.calibration
        if calibration is None:
            return []
        entities: list[Entity] = []
        if calibration.outdoor_offset is not None:
            entities.append(RehauOutdoorOffset(coordinator))
        for zone, row in calibration.rooms.items():
            if zone not in coordinator.state.room_names:
                continue
            entities.append(RehauRoomOffset(coordinator, zone, humidity=False))
            if row.humidity_offset is not None:
                entities.append(RehauRoomOffset(coordinator, zone, humidity=True))
        return entities

    async_add_dynamic_entities(
        entry, entry.runtime_data.coordinator, async_add_entities, build
    )


class _OffsetMixin(NumberEntity):
    """Shared limits and state for an offset backed by a SettingValue.

    The limits come from the device's input; the fallbacks are what fw 6.15
    declares, for a page that would ever omit them.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def _offset(self) -> SettingValue | None:
        raise NotImplementedError

    @property
    @override
    def native_value(self) -> float | None:
        """Return the offset."""
        offset = self._offset()
        return None if offset is None else float(offset.value)

    @property
    @override
    def native_min_value(self) -> float:
        """Return the device's minimum."""
        offset = self._offset()
        return offset.minimum if offset and offset.minimum is not None else -5.0

    @property
    @override
    def native_max_value(self) -> float:
        """Return the device's maximum."""
        offset = self._offset()
        return offset.maximum if offset and offset.maximum is not None else 5.0

    @property
    @override
    def native_step(self) -> float:
        """Return the device's step."""
        offset = self._offset()
        return offset.step if offset and offset.step is not None else 0.1


class RehauOutdoorOffset(RehauEntity, _OffsetMixin):
    """Offset of the outdoor probe."""

    _attr_translation_key = "outdoor_offset"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: RehauCoordinator) -> None:
        """Create the number."""
        super().__init__(coordinator, "outdoor_offset")

    @override
    def _offset(self) -> SettingValue | None:
        calibration = self.coordinator.state.calibration
        return None if calibration is None else calibration.outdoor_offset

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Write the offset."""
        await self.coordinator.async_set_calibration(outdoor_offset=value)


class RehauRoomOffset(RehauRoomEntity, _OffsetMixin):
    """Offset of a room's temperature or humidity probe."""

    def __init__(
        self, coordinator: RehauCoordinator, zone: int, *, humidity: bool
    ) -> None:
        """Create the number."""
        key = "humidity_offset" if humidity else "temperature_offset"
        super().__init__(coordinator, zone, key)
        self.humidity = humidity
        self._attr_translation_key = key
        self._attr_native_unit_of_measurement = (
            PERCENTAGE if humidity else UnitOfTemperature.CELSIUS
        )

    @override
    def _offset(self) -> SettingValue | None:
        calibration = self.coordinator.state.calibration
        row = None if calibration is None else calibration.rooms.get(self.zone)
        if row is None:
            return None
        return row.humidity_offset if self.humidity else row.temperature_offset

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Write the offset."""
        if self.humidity:
            await self.coordinator.async_set_calibration(
                humidity_offsets={self.zone: value}
            )
        else:
            await self.coordinator.async_set_calibration(
                temperature_offsets={self.zone: value}
            )
