"""The Rehau Nea Smart integration."""
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .auth import RehauAuthClient
from .const import CONF_INSTALL_ID, DOMAIN
from .coordinator import RehauDataCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rehau Nea Smart from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    install_id = entry.data.get(CONF_INSTALL_ID)

    # Create aiohttp session
    session = aiohttp.ClientSession()

    # Initialize auth client
    auth_client = RehauAuthClient(session)

    try:
        # Perform login
        _LOGGER.info("Logging in to Rehau Nea Smart")
        await auth_client.start_authorization_flow()
        success = await auth_client.login(email, password)

        if not success:
            _LOGGER.error("Login failed")
            await session.close()
            raise ConfigEntryNotReady("Login failed")

        # Note: For production, you'd need to handle MFA properly
        # This assumes MFA is completed or not required
        # You may need to add MFA handling to config flow

        # For now, we'll try to continue without MFA if possible
        # In a real deployment, you'd need proper MFA handling

        _LOGGER.info("Getting tokens")
        # This might fail if MFA is required - handle appropriately
        try:
            await auth_client.complete_mfa_login()
            await auth_client.get_tokens()
        except Exception as e:
            _LOGGER.error(f"Token exchange failed, MFA might be required: {e}")
            await session.close()
            raise ConfigEntryNotReady("MFA required - not yet supported in config flow")

        # Introspect token to ensure it's valid
        await auth_client.introspect_token()

        # Get installation data
        _LOGGER.info("Fetching installation data")
        install_data = await auth_client.get_install_data(email, install_id)

        # Extract device ID
        installs = install_data.get("user", {}).get("installs", [])
        if not installs:
            _LOGGER.error("No installations found")
            await session.close()
            raise ConfigEntryNotReady("No installations found")

        device_id = installs[0].get("unique")

        # Create coordinator
        coordinator = RehauDataCoordinator(
            hass,
            auth_client,
            email,
            device_id,
            {"install_id": install_id},
        )
        coordinator.install_data = install_data

        # Connect to MQTT
        _LOGGER.info("Connecting to MQTT")
        await coordinator.connect_mqtt()

        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

        # Forward entry setup to platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        return True

    except Exception as err:
        _LOGGER.error(f"Error setting up Rehau Nea Smart: {err}")
        await session.close()
        raise ConfigEntryNotReady(f"Error setting up integration: {err}")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: RehauDataCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.disconnect()
        await coordinator.auth_client.session.close()

    return unload_ok
