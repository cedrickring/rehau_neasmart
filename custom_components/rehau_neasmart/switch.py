"""Switches: room display lock, adaptive start, open-window detection, light."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RehauConfigEntry
from .api.models import RoomSetup
from .coordinator import RehauCoordinator
from .entity import RehauRoomEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class RehauFlagSwitchDescription(SwitchEntityDescription):
    """A flag on the room set-up form."""

    value_fn: Callable[[RoomSetup], bool]
    set_fn: Callable[[RehauCoordinator, int, bool], Coroutine[Any, Any, None]]


FLAG_SWITCHES: tuple[RehauFlagSwitchDescription, ...] = (
    RehauFlagSwitchDescription(
        key="lock",
        translation_key="lock",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda setup: setup.lock,
        set_fn=lambda coordinator, zone, on: coordinator.async_set_room_flags(
            zone, lock=on
        ),
    ),
    RehauFlagSwitchDescription(
        key="auto_start",
        translation_key="auto_start",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda setup: setup.auto_start,
        set_fn=lambda coordinator, zone, on: coordinator.async_set_room_flags(
            zone, auto_start=on
        ),
    ),
    RehauFlagSwitchDescription(
        key="window_detection",
        translation_key="window_detection",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda setup: setup.window_detection,
        set_fn=lambda coordinator, zone, on: coordinator.async_set_room_flags(
            zone, window_detection=on
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RehauConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add flag switches for every room with a set-up form, light switches where wired."""

    def build(coordinator: RehauCoordinator) -> list[Entity]:
        state = coordinator.state
        entities: list[Entity] = [
            RehauFlagSwitch(coordinator, zone, description)
            for zone in state.setups
            for description in FLAG_SWITCHES
        ]
        entities.extend(
            RehauLightSwitch(coordinator, zone)
            for zone, room in state.rooms.items()
            if room.has_light
        )
        return entities

    async_add_dynamic_entities(
        entry, entry.runtime_data.coordinator, async_add_entities, build
    )


class RehauFlagSwitch(RehauRoomEntity, SwitchEntity):
    """A room set-up flag."""

    entity_description: RehauFlagSwitchDescription

    def __init__(
        self,
        coordinator: RehauCoordinator,
        zone: int,
        description: RehauFlagSwitchDescription,
    ) -> None:
        """Create the switch."""
        super().__init__(coordinator, zone, description.key)
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the flag as last read."""
        setup = self.coordinator.state.setups.get(self.zone)
        return None if setup is None else self.entity_description.value_fn(setup)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the flag."""
        await self.entity_description.set_fn(self.coordinator, self.zone, True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear the flag."""
        await self.entity_description.set_fn(self.coordinator, self.zone, False)


class RehauLightSwitch(RehauRoomEntity, SwitchEntity):
    """The light relay a room can drive."""

    _attr_translation_key = "light"

    def __init__(self, coordinator: RehauCoordinator, zone: int) -> None:
        """Create the switch."""
        super().__init__(coordinator, zone, "light")

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the light state."""
        return room.light if (room := self.room) else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the light on."""
        await self.coordinator.async_set_room_light(self.zone, True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the light off."""
        await self.coordinator.async_set_room_light(self.zone, False)
