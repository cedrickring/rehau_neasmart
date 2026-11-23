"""Base entities and dynamic room-entity creation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, override

from homeassistant.core import callback
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import RoomDetail, UModuleIO
from .const import DOMAIN
from .coordinator import RehauCoordinator, RehauIOCoordinator

if TYPE_CHECKING:
    from . import RehauConfigEntry


class RehauEntity(CoordinatorEntity[RehauCoordinator]):
    """An entity of the base station itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RehauCoordinator, key: str) -> None:
        """Attach the entity to the base station device."""
        super().__init__(coordinator)
        base_id = coordinator.config_entry.unique_id
        self._attr_unique_id = f"{base_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, str(base_id))})


class RehauRoomEntity(CoordinatorEntity[RehauCoordinator]):
    """An entity of one room (zone), shown as a part of the base station."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RehauCoordinator, zone: int, key: str) -> None:
        """Attach the entity to the room's child device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        base_id = entry.unique_id
        self.zone = zone
        self._attr_unique_id = f"{base_id}_{zone}_{key}"
        self._attr_device_info = ChildDeviceInfo(
            identifiers={(DOMAIN, f"{base_id}_{zone}")},
            name=coordinator.state.room_names.get(zone, f"Zone {zone}"),
            parent_device_id=entry.runtime_data.base_device_id,
        )

    @property
    def room(self) -> RoomDetail | None:
        """Return the room's last reading."""
        return self.coordinator.state.rooms.get(self.zone)

    @property
    @override
    def available(self) -> bool:
        """Return False once the zone has gone from the device."""
        return super().available and self.zone in self.coordinator.state.room_names


class RehauIOEntity(CoordinatorEntity[RehauIOCoordinator]):
    """An I/O channel of the base station (module None) or of a U-module."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: RehauIOCoordinator, module: int | None, key: str
    ) -> None:
        """Attach the channel to the base station or to its U-module device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        base_id = entry.unique_id
        self.module = module
        if module is None:
            self._attr_unique_id = f"{base_id}_io_master_{key}"
            self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, str(base_id))})
            return
        firmware = entry.runtime_data.coordinator.state.system.firmware
        self._attr_unique_id = f"{base_id}_io_umodule{module}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{base_id}_umodule_{module}")},
            manufacturer="REHAU",
            model="Nea Smart 2.0 U-module",
            translation_key="umodule",
            translation_placeholders={"index": str(module)},
            sw_version=firmware.umodules.get(module),
            via_device_id=entry.runtime_data.base_device_id,
        )

    @property
    def umodule(self) -> UModuleIO | None:
        """Return this channel's U-module reading; None for master channels."""
        if self.module is None:
            return None
        return self.coordinator.data.umodules.get(self.module)


@callback
def async_add_dynamic_entities[CoordinatorT: (RehauCoordinator, RehauIOCoordinator)](
    entry: RehauConfigEntry,
    coordinator: CoordinatorT,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[CoordinatorT], Iterable[Entity]],
) -> None:
    """Add entities now and whenever an update makes new ones possible.

    `build` returns every entity the current state supports; entities whose
    unique id was added before are skipped. This picks up rooms added on the
    device and capabilities that only show in one season (fancoils).
    """
    added: set[str] = set()

    @callback
    def add_new() -> None:
        new = [
            entity
            for entity in build(coordinator)
            if entity.unique_id is not None and entity.unique_id not in added
        ]
        added.update(entity.unique_id for entity in new if entity.unique_id)
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))
