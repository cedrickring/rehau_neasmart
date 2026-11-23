"""Binary sensors: active alarms, fancoil running, flap, digital I/O."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .api.models import IOSnapshot, RoomDetail
from .coordinator import RehauCoordinator, RehauIOCoordinator
from .entity import (
    RehauEntity,
    RehauIOEntity,
    RehauRoomEntity,
    async_add_dynamic_entities,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RehauRoomBinarySensorDescription(BinarySensorEntityDescription):
    """A room binary sensor."""

    value_fn: Callable[[RoomDetail], bool]
    exists_fn: Callable[[RoomDetail], bool]


ROOM_BINARY_SENSORS: tuple[RehauRoomBinarySensorDescription, ...] = (
    RehauRoomBinarySensorDescription(
        key="fan_running",
        translation_key="fan_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.fan_running,
        exists_fn=lambda room: room.has_fan,
    ),
    RehauRoomBinarySensorDescription(
        key="flap",
        translation_key="flap",
        device_class=BinarySensorDeviceClass.OPENING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.flap == 1,
        exists_fn=lambda room: room.has_flap,
    ),
)

# (channel group, translation key) per I/O list; RZ exists only on the master.
_MASTER_CHANNELS = (("rz", "zone_valve"), ("relay", "relay"), ("di", "digital_input"))
_UMODULE_CHANNELS = (("relay", "relay"), ("di", "digital_input"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add binary sensors."""

    def build(coordinator: RehauCoordinator) -> list[Entity]:
        entities: list[Entity] = [RehauAlarmSensor(coordinator)]
        entities.extend(
            RehauRoomBinarySensor(coordinator, zone, description)
            for zone, room in coordinator.state.rooms.items()
            for description in ROOM_BINARY_SENSORS
            if description.exists_fn(room)
        )
        return entities

    async_add_dynamic_entities(
        entry, entry.runtime_data.coordinator, async_add_entities, build
    )

    if (io := entry.runtime_data.io_coordinator) is not None:

        def build_io(coordinator: RehauIOCoordinator) -> list[Entity]:
            data = coordinator.data
            entities: list[Entity] = [
                RehauDigitalChannel(coordinator, None, group, key, index)
                for group, key in _MASTER_CHANNELS
                for index in range(len(getattr(data.master, group)))
            ]
            entities.extend(
                RehauDigitalChannel(coordinator, module, group, key, index)
                for module, channels in data.umodules.items()
                for group, key in _UMODULE_CHANNELS
                for index in range(len(getattr(channels, group)))
            )
            return entities

        async_add_dynamic_entities(entry, io, async_add_entities, build_io)


class RehauAlarmSensor(RehauEntity, BinarySensorEntity):
    """On while any alarm in the log has no end time."""

    _attr_translation_key = "alarms"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: RehauCoordinator) -> None:
        """Create the alarm sensor."""
        super().__init__(coordinator, "alarms_active")

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True while an alarm is active; unknown before the log was read."""
        messages = self.coordinator.state.messages
        if messages is None:
            return None
        return any(message.active for message in messages)


class RehauRoomBinarySensor(RehauRoomEntity, BinarySensorEntity):
    """A room binary sensor."""

    entity_description: RehauRoomBinarySensorDescription

    def __init__(
        self,
        coordinator: RehauCoordinator,
        zone: int,
        description: RehauRoomBinarySensorDescription,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, zone, description.key)
        self.entity_description = description

    @property
    @override
    def available(self) -> bool:
        """Return False while the device does not show this for the room."""
        room = self.room
        return (
            super().available
            and room is not None
            and self.entity_description.exists_fn(room)
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state."""
        room = self.room
        return None if room is None else self.entity_description.value_fn(room)


class RehauDigitalChannel(RehauIOEntity, BinarySensorEntity):
    """A relay, zone valve output or digital input."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: RehauIOCoordinator,
        module: int | None,
        group: str,
        translation_key: str,
        index: int,
    ) -> None:
        """Create the channel sensor; index is 0-based, names are 1-based."""
        super().__init__(coordinator, module, f"{group}_{index + 1}")
        self.group = group
        self.index = index
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = {"index": str(index + 1)}

    def _values(self, data: IOSnapshot) -> tuple[float, ...]:
        if self.module is None:
            return getattr(data.master, self.group)
        channels = self.umodule
        return () if channels is None else getattr(channels, self.group)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True when the channel reads non-zero."""
        values = self._values(self.coordinator.data)
        return None if self.index >= len(values) else values[self.index] != 0
