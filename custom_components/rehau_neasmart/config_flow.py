"""Config flow for Rehau Nea Smart integration."""
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .auth import RehauAuthClient
from .const import CONF_INSTALL_ID, DEFAULT_INSTALL_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class RehauConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rehau Nea Smart."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.data = {}
        self.auth_client = None
        self.session = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            self.data[CONF_EMAIL] = user_input[CONF_EMAIL]
            self.data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            self.data[CONF_INSTALL_ID] = user_input.get(CONF_INSTALL_ID, DEFAULT_INSTALL_ID)

            # Test credentials
            self.session = aiohttp.ClientSession()
            self.auth_client = RehauAuthClient(self.session)

            try:
                await self.auth_client.start_authorization_flow()
                success = await self.auth_client.login(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )

                if not success:
                    errors["base"] = "invalid_auth"
                else:
                    # MFA is required - proceed to MFA step
                    await self.auth_client.initiate_mfa_email()
                    return await self.async_step_mfa()

            except Exception as e:
                _LOGGER.error(f"Error during login: {e}")
                errors["base"] = "cannot_connect"
                await self.session.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_INSTALL_ID, default=DEFAULT_INSTALL_ID): str,
                }
            ),
            errors=errors,
        )

    async def async_step_mfa(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle MFA code entry."""
        errors = {}

        if user_input is not None:
            try:
                # Verify MFA code
                success = await self.auth_client.verify_mfa_code(user_input["mfa_code"])

                if not success:
                    errors["base"] = "invalid_mfa"
                else:
                    # Complete login and get tokens
                    await self.auth_client.complete_mfa_login()
                    await self.auth_client.get_tokens()

                    # Create entry
                    await self.session.close()

                    await self.async_set_unique_id(self.data[CONF_EMAIL])
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Rehau ({self.data[CONF_EMAIL]})",
                        data=self.data,
                    )

            except Exception as e:
                _LOGGER.error(f"Error during MFA: {e}")
                errors["base"] = "invalid_mfa"

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema(
                {
                    vol.Required("mfa_code"): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "email": self.data[CONF_EMAIL],
            },
        )
