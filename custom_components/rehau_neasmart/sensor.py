"""Sensors: outdoor temperature, alarms, room humidity, fancoil speed, analog I/O."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .api.models import RoomDetail
from .coordinator import RehauCoordinator, RehauIOCoordinator, RehauState
from .entity import (
    RehauEntity,
    RehauIOEntity,
    RehauRoomEntity,
    async_add_dynamic_entities,
)

PARALLEL_UPDATES = 0

FAN_SPEEDS = ["off", "low", "medium", "high", "max"]


@dataclass(frozen=True, kw_only=True)
class RehauSensorDescription(SensorEntityDescription):
    """A base-station sensor."""

    value_fn: Callable[[RehauState], float | None]
    exists_fn: Callable[[RehauState], bool] = lambda state: True


@dataclass(frozen=True, kw_only=True)
class RehauRoomSensorDescription(SensorEntityDescription):
    """A room sensor."""

    value_fn: Callable[[RoomDetail], float | str | None]
    exists_fn: Callable[[RoomDetail], bool]


def _fan_speed(room: RoomDetail) -> str:
    """Return the speed the fancoil runs at; a configured speed counts only while running."""
    if not room.fan_running:
        return "off"
    return FAN_SPEEDS[min(max(room.fan, 0), len(FAN_SPEEDS) - 1)]


SENSORS: tuple[RehauSensorDescription, ...] = (
    RehauSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda state: (
            state.dashboard.outdoor_temperature if state.dashboard else None
        ),
        # Installations without an outdoor sensor show no reading at all.
        exists_fn=lambda state: (
            state.dashboard is not None
            and state.dashboard.outdoor_temperature is not None
        ),
    ),
    RehauSensorDescription(
        key="active_alarms",
        translation_key="active_alarms",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: (
            None
            if state.messages is None
            else sum(message.active for message in state.messages)
        ),
    ),
)

ROOM_SENSORS: tuple[RehauRoomSensorDescription, ...] = (
    RehauRoomSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda room: room.humidity,
        exists_fn=lambda room: room.humidity is not None,
    ),
    RehauRoomSensorDescription(
        key="fan_speed",
        translation_key="fan_speed",
        device_class=SensorDeviceClass.ENUM,
        options=FAN_SPEEDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_fan_speed,
        exists_fn=lambda room: room.has_fan,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors as the device shows the readings for them."""

    def build(coordinator: RehauCoordinator) -> list[Entity]:
        state = coordinator.state
        entities: list[Entity] = [
            RehauSensor(coordinator, description)
            for description in SENSORS
            if description.exists_fn(state)
        ]
        entities.extend(
            RehauRoomSensor(coordinator, zone, description)
            for zone, room in state.rooms.items()
            for description in ROOM_SENSORS
            if description.exists_fn(room)
        )
        return entities

    async_add_dynamic_entities(
        entry, entry.runtime_data.coordinator, async_add_entities, build
    )

    if (io := entry.runtime_data.io_coordinator) is not None:

        def build_io(coordinator: RehauIOCoordinator) -> list[Entity]:
            entities: list[Entity] = []
            for module, channels in coordinator.data.umodules.items():
                entities.extend(
                    RehauAnalogInput(coordinator, module, index)
                    for index in range(len(channels.ai))
                )
                entities.append(RehauAnalogOutput(coordinator, module))
            return entities

        async_add_dynamic_entities(entry, io, async_add_entities, build_io)


class RehauSensor(RehauEntity, SensorEntity):
    """A base-station sensor."""

    entity_description: RehauSensorDescription

    def __init__(
        self, coordinator: RehauCoordinator, description: RehauSensorDescription
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> float | None:
        """Return the reading."""
        return self.entity_description.value_fn(self.coordinator.state)


class RehauRoomSensor(RehauRoomEntity, SensorEntity):
    """A room sensor."""

    entity_description: RehauRoomSensorDescription

    def __init__(
        self,
        coordinator: RehauCoordinator,
        zone: int,
        description: RehauRoomSensorDescription,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, zone, description.key)
        self.entity_description = description

    @property
    @override
    def available(self) -> bool:
        """Return False while the room does not show this reading."""
        room = self.room
        return (
            super().available
            and room is not None
            and self.entity_description.exists_fn(room)
        )

    @property
    @override
    def native_value(self) -> float | str | None:
        """Return the reading."""
        room = self.room
        return None if room is None else self.entity_description.value_fn(room)


class RehauAnalogInput(RehauIOEntity, SensorEntity):
    """A U-module analog input, in °C; "--" on the device reads as unknown."""

    _attr_translation_key = "analog_input"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self, coordinator: RehauIOCoordinator, module: int, index: int
    ) -> None:
        """Create the input sensor."""
        super().__init__(coordinator, module, f"ai_{index + 1}")
        self.index = index
        self._attr_translation_placeholders = {"index": str(index + 1)}

    @property
    @override
    def native_value(self) -> float | None:
        """Return the input temperature."""
        channels = self.umodule
        if channels is None or self.index >= len(channels.ai):
            return None
        return channels.ai[self.index]


class RehauAnalogOutput(RehauIOEntity, SensorEntity):
    """A U-module modulating output, in percent."""

    _attr_translation_key = "analog_output"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: RehauIOCoordinator, module: int) -> None:
        """Create the output sensor."""
        super().__init__(coordinator, module, "ao")

    @property
    @override
    def native_value(self) -> float | None:
        """Return the output level."""
        channels = self.umodule
        return None if channels is None else channels.ao
