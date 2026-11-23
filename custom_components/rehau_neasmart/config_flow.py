"""Config flow for the REHAU Nea Smart 2.0 integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import probatio

from . import RehauConfigEntry
from .api.client import RehauClient
from .api.device import RehauDevice
from .api.exceptions import RehauConnectionError, RehauError
from .const import (
    CONF_EXPOSE_CALIBRATION,
    CONF_EXPOSE_IO,
    CONF_INSTALLER_CODE,
    DEFAULT_EXPOSE_CALIBRATION,
    DEFAULT_EXPOSE_IO,
    DOMAIN,
    LOGGER,
)
from .helpers import entry_unique_id

# The installer field on the device's own login form has maxlength="8".
INSTALLER_CODE_MAX_LENGTH = 8

TITLE = "REHAU Nea Smart 2.0"


def _schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, "")
            ): TextSelector(),
            probatio.Optional(
                CONF_INSTALLER_CODE,
                description={"suggested_value": defaults.get(CONF_INSTALLER_CODE)},
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        }
    )


async def _validate(
    flow: ConfigFlow, user_input: dict[str, Any]
) -> tuple[str | None, dict[str, str]]:
    """Read the device once; return its unique id and any form errors.

    The installer code cannot be checked: the device answers the login the
    same way whether the code is right or wrong.
    """
    code = (user_input.get(CONF_INSTALLER_CODE) or "").strip()
    if len(code) > INSTALLER_CODE_MAX_LENGTH:
        return None, {CONF_INSTALLER_CODE: "installer_code_too_long"}
    client = RehauClient(
        async_get_clientsession(flow.hass), user_input[CONF_HOST].strip()
    )
    device = RehauDevice(client)
    try:
        system = await device.fetch_system_info()
        rooms = await device.fetch_room_list()
    except RehauConnectionError:
        return None, {"base": "cannot_connect"}
    except RehauError:
        return None, {"base": "invalid_device"}
    except Exception:
        LOGGER.exception("Unexpected error validating the base station")
        return None, {"base": "unknown"}
    if not rooms:
        return None, {"base": "no_rooms"}
    return entry_unique_id(system.unique_code), {}


def _entry_data(user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {CONF_HOST: user_input[CONF_HOST].strip()}
    if code := (user_input.get(CONF_INSTALLER_CODE) or "").strip():
        data[CONF_INSTALLER_CODE] = code
    return data


class RehauConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a base station by address."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: RehauConfigEntry) -> RehauOptionsFlow:
        """Return the options flow."""
        return RehauOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the base station's address and optional installer code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id, errors = await _validate(self, user_input)
            if unique_id is not None:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST].strip()}
                )
                return self.async_create_entry(
                    title=TITLE, data=_entry_data(user_input)
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or installer code of the same base station."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id, errors = await _validate(self, user_input)
            if unique_id is not None:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data=_entry_data(user_input)
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or entry.data),
            errors=errors,
        )


class RehauOptionsFlow(OptionsFlowWithReload):
    """Choose which installer data becomes entities."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_EXPOSE_IO,
                        default=options.get(CONF_EXPOSE_IO, DEFAULT_EXPOSE_IO),
                    ): BooleanSelector(),
                    probatio.Required(
                        CONF_EXPOSE_CALIBRATION,
                        default=options.get(
                            CONF_EXPOSE_CALIBRATION, DEFAULT_EXPOSE_CALIBRATION
                        ),
                    ): BooleanSelector(),
                }
            ),
        )
