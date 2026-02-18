"""The Rehau Nea Smart integration."""
import logging
from datetime import datetime

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
    _LOGGER.info("Setting up Rehau Nea Smart integration")
    email = entry.data[CONF_EMAIL]
    install_id = entry.data.get(CONF_INSTALL_ID)
    _LOGGER.debug(f"Configuration: email={email}, install_id={install_id}")

    # Create aiohttp session
    session = aiohttp.ClientSession()

    # Initialize auth client
    auth_client = RehauAuthClient(session)

    try:
        # Check if we have saved tokens from config flow
        if "access_token" in entry.data and "refresh_token" in entry.data:
            _LOGGER.info("Using saved tokens from config entry")
            
            # Restore token state
            auth_client.access_token = entry.data.get("access_token")
            auth_client.refresh_token = entry.data.get("refresh_token")
            auth_client.sid = entry.data.get("sid")
            
            # Parse expires_at
            expires_at_str = entry.data.get("expires_at")
            if expires_at_str:
                auth_client.expires_at = datetime.fromisoformat(expires_at_str)
            
            # Verify token is still valid (and refresh if needed)
            try:
                await auth_client.introspect_token()
            except Exception as e:
                _LOGGER.warning(f"Saved token invalid, attempting refresh: {e}")
                try:
                    await auth_client.refresh_access_token()
                    # Update config entry with new tokens
                    new_data = dict(entry.data)
                    new_data["access_token"] = auth_client.access_token
                    new_data["refresh_token"] = auth_client.refresh_token
                    new_data["sid"] = auth_client.sid
                    new_data["expires_at"] = auth_client.expires_at.isoformat() if auth_client.expires_at else None
                    hass.config_entries.async_update_entry(entry, data=new_data)
                    _LOGGER.info("Token refreshed successfully")
                except Exception as refresh_error:
                    _LOGGER.error(f"Token refresh failed: {refresh_error}")
                    await session.close()
                    raise ConfigEntryNotReady("Token refresh failed - please reconfigure the integration")
        else:
            # Legacy: No saved tokens, need to re-authenticate (will fail without MFA)
            _LOGGER.warning("No saved tokens found - integration needs to be reconfigured with MFA support")
            await session.close()
            raise ConfigEntryNotReady("Please remove and re-add the integration to complete MFA authentication")

        # Get installation data
        _LOGGER.info("Fetching installation data")
        install_data = await auth_client.get_install_data(email, install_id)

        # Extract device ID
        installs = install_data.get("user", {}).get("installs", [])
        if not installs:
            _LOGGER.error("No installations found in API response")
            await session.close()
            raise ConfigEntryNotReady("No installations found")

        device_id = installs[0].get("unique")
        _LOGGER.debug(f"Using device_id: {device_id}")

        # Create coordinator
        _LOGGER.debug("Creating data coordinator")
        coordinator = RehauDataCoordinator(
            hass,
            auth_client,
            email,
            device_id,
            {"install_id": install_id},
        )
        coordinator.install_data = install_data

        # Connect to MQTT
        _LOGGER.info("Connecting to MQTT broker")
        await coordinator.connect_mqtt()

        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

        # Forward entry setup to platforms
        _LOGGER.info("Setting up climate platform")
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        _LOGGER.info("Rehau Nea Smart integration setup complete")
        return True

    except Exception as err:
        _LOGGER.error(f"Error setting up Rehau Nea Smart: {err}")
        await session.close()
        raise ConfigEntryNotReady(f"Error setting up integration: {err}")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Rehau Nea Smart integration")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: RehauDataCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.disconnect()
        await coordinator.auth_client.session.close()
        _LOGGER.info("Rehau Nea Smart integration unloaded successfully")

    return unload_ok
