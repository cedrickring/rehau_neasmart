"""The REHAU Nea Smart 2.0 integration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api.client import FetchRecord, RehauClient
from .api.device import RehauDevice
from .api.exceptions import RehauError
from .const import (
    CONF_EXPOSE_IO,
    CONF_INSTALLER_CODE,
    DEFAULT_EXPOSE_IO,
    DOMAIN,
    LOGGER,
)
from .coordinator import RehauCoordinator, RehauIOCoordinator
from .services import async_setup_services

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Requests kept for diagnostics, as in the bridge's telemetry buffer.
FETCH_HISTORY = 15


@dataclass(slots=True)
class RehauRuntimeData:
    """What a loaded config entry holds."""

    device: RehauDevice
    coordinator: RehauCoordinator
    io_coordinator: RehauIOCoordinator | None
    base_device_id: str


type RehauConfigEntry = ConfigEntry[RehauRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def _async_close(device: RehauDevice) -> None:
    """Leave installer mode; the device keeps it on for every client otherwise."""
    try:
        await device.close()
    except RehauError as err:
        LOGGER.warning("Could not turn installer mode off: %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: RehauConfigEntry) -> bool:
    """Set up a base station from a config entry."""
    fetches: deque[FetchRecord] = deque(maxlen=FETCH_HISTORY)
    client = RehauClient(
        async_get_clientsession(hass), entry.data[CONF_HOST], on_fetch=fetches.append
    )
    device = RehauDevice(client, entry.data.get(CONF_INSTALLER_CODE))
    coordinator = RehauCoordinator(hass, entry, device, fetches)
    io_coordinator = (
        RehauIOCoordinator(hass, entry, device)
        if device.has_installer and entry.options.get(CONF_EXPOSE_IO, DEFAULT_EXPOSE_IO)
        else None
    )
    try:
        await coordinator.async_config_entry_first_refresh()
        if io_coordinator is not None:
            await io_coordinator.async_config_entry_first_refresh()
    except Exception:
        await _async_close(device)
        raise

    system = coordinator.state.system
    base = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer="REHAU",
        model="Nea Smart 2.0 base station",
        name=entry.title,
        sw_version=system.firmware.master or None,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
    entry.runtime_data = RehauRuntimeData(
        device=device,
        coordinator=coordinator,
        io_coordinator=io_coordinator,
        base_device_id=base.id,
    )

    async def _async_on_stop(_: Event) -> None:
        await _async_close(device)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RehauConfigEntry) -> bool:
    """Unload a config entry and leave installer mode."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await _async_close(entry.runtime_data.device)
    return unloaded
