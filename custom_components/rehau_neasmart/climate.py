"""Climate platform for Rehau Nea Smart."""
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RehauDataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rehau climate entities."""
    coordinator: RehauDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Extract zones from installation data
    install_data = coordinator.install_data
    installs = install_data.get("user", {}).get("installs", [])

    if not installs:
        _LOGGER.error("No installations found")
        return

    install = installs[0]
    groups = install.get("groups", [])

    entities = []

    if groups and groups[0].get("zones"):
        zones = groups[0]["zones"]
        for zone in zones:
            zone_name = zone.get("name", "Unknown")
            zone_number = zone.get("number")
            channels = zone.get("channels", [])

            if channels:
                channel = channels[0]
                entities.append(RehauClimate(coordinator, zone_name, zone_number, channel))

    async_add_entities(entities)


class RehauClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Rehau thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(
        self,
        coordinator: RehauDataCoordinator,
        zone_name: str,
        zone_number: int,
        channel_data: dict[str, Any],
    ):
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._zone_number = zone_number
        self._channel_data = channel_data
        self._channel_id = channel_data.get("number")

        self._attr_name = f"Rehau {zone_name}"
        self._attr_unique_id = f"rehau_{coordinator.device_id}_{self._channel_id}"

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        temp_zone = self._channel_data.get("temp_zone")
        if temp_zone is not None:
            return round(self.coordinator.api_value_to_celsius(temp_zone), 1)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        setpoint = self._channel_data.get("setpoint_used")
        if setpoint is not None:
            return round(self.coordinator.api_value_to_celsius(setpoint), 1)
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        # Check if heating is active based on demand
        demand = self._channel_data.get("demand", 0)
        if demand > 0:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            "zone_number": self._zone_number,
            "channel_id": self._channel_id,
            "demand": self._channel_data.get("demand", 0),
            "setpoint_h_normal": round(
                self.coordinator.api_value_to_celsius(self._channel_data.get("setpoint_h_normal", 0)), 1
            ),
            "setpoint_h_reduced": round(
                self.coordinator.api_value_to_celsius(self._channel_data.get("setpoint_h_reduced", 0)), 1
            ),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.info(f"Setting temperature for {self._zone_name} to {temperature}°C")

        try:
            await self.coordinator.set_temperature(self._zone_number, temperature)

            # Update local state immediately for better UX
            api_value = self.coordinator.celsius_to_api_value(temperature)
            self._channel_data["setpoint_used"] = api_value

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error(f"Failed to set temperature: {err}")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        # For now, we don't support changing HVAC mode
        # The system is always in heating mode, controlled by setpoint
        _LOGGER.warning(f"HVAC mode change not supported: {hvac_mode}")

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        limit_h_min = self._channel_data.get("limit_h_min")
        if limit_h_min:
            return round(self.coordinator.api_value_to_celsius(limit_h_min), 1)
        return 5.0

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        limit_h_max = self._channel_data.get("limit_h_max")
        if limit_h_max:
            return round(self.coordinator.api_value_to_celsius(limit_h_max), 1)
        return 35.0
