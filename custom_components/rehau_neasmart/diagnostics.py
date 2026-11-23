"""Diagnostics: everything read from the device plus the recent request log."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import RehauConfigEntry
from .const import CONF_INSTALLER_CODE

TO_REDACT = {CONF_INSTALLER_CODE, "unique_code", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RehauConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    io = runtime.io_coordinator
    return async_redact_data(
        {
            "entry": {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            "installer_open": runtime.device.installer_open,
            "last_update_success": coordinator.last_update_success,
            "state": asdict(coordinator.state),
            "io": asdict(io.data) if io is not None and io.data is not None else None,
            "recent_requests": [asdict(record) for record in coordinator.fetches],
        },
        TO_REDACT,
    )
