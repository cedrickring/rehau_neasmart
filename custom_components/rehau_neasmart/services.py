"""Actions for what has no entity: programs, the alarm log, installer settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.selector import ConfigEntrySelector
import probatio

from .api.codecs import bits_to_intervals, intervals_to_bits
from .api.device import DAILY_PROGRAMS, WEEKLY_PROGRAMS
from .api.models import InstallerSettingsGroup
from .const import DOMAIN

if TYPE_CHECKING:
    from . import RehauConfigEntry
    from .coordinator import RehauCoordinator

ATTR_PROGRAM = "program"
ATTR_PERIODS = "periods"
ATTR_START = "start"
ATTR_END = "end"
ATTR_GROUP = "group"
ATTR_VALUES = "values"
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

SERVICE_GET_PROGRAMS = "get_programs"
SERVICE_SET_DAILY_PROGRAM = "set_daily_program"
SERVICE_SET_WEEKLY_PROGRAM = "set_weekly_program"
SERVICE_GET_MESSAGES = "get_messages"
SERVICE_GET_INSTALLER_SETTINGS = "get_installer_settings"
SERVICE_SET_INSTALLER_SETTINGS = "set_installer_settings"

_ENTRY = {
    probatio.Required(ATTR_CONFIG_ENTRY_ID): ConfigEntrySelector(
        {"integration": DOMAIN}
    )
}

ENTRY_SCHEMA = probatio.Schema(_ENTRY)

SET_DAILY_PROGRAM_SCHEMA = probatio.Schema(
    {
        **_ENTRY,
        probatio.Required(ATTR_PROGRAM): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=DAILY_PROGRAMS)
        ),
        probatio.Required(ATTR_PERIODS): [
            probatio.Schema(
                {
                    probatio.Required(ATTR_START): cv.string,
                    probatio.Required(ATTR_END): cv.string,
                }
            )
        ],
    }
)

_DAILY_ID = probatio.All(
    probatio.Coerce(int), probatio.Range(min=1, max=DAILY_PROGRAMS)
)

SET_WEEKLY_PROGRAM_SCHEMA = probatio.Schema(
    {
        **_ENTRY,
        probatio.Required(ATTR_PROGRAM): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=WEEKLY_PROGRAMS)
        ),
        **{probatio.Optional(day): _DAILY_ID for day in WEEKDAYS},
    }
)

GROUP_SCHEMA = probatio.Schema(
    {
        **_ENTRY,
        probatio.Required(ATTR_GROUP): probatio.In(
            [group.value for group in InstallerSettingsGroup]
        ),
    }
)

SET_INSTALLER_SETTINGS_SCHEMA = probatio.Schema(
    {
        **_ENTRY,
        probatio.Required(ATTR_GROUP): probatio.In(
            [group.value for group in InstallerSettingsGroup]
        ),
        probatio.Required(ATTR_VALUES): probatio.All(
            {cv.string: probatio.Any(bool, probatio.Coerce(float))},
            probatio.Length(min=1),
        ),
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> RehauCoordinator:
    entry: RehauConfigEntry = service.async_get_config_entry(
        hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID]
    )
    return entry.runtime_data.coordinator


def _installer_coordinator(hass: HomeAssistant, call: ServiceCall) -> RehauCoordinator:
    coordinator = _coordinator(hass, call)
    if not coordinator.device.has_installer:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="installer_required"
        )
    return coordinator


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def get_programs(call: ServiceCall) -> ServiceResponse:
        state = _coordinator(hass, call).state
        return {
            "daily": [
                {
                    "program": program.id,
                    ATTR_PERIODS: [
                        {ATTR_START: start, ATTR_END: end}
                        for start, end in bits_to_intervals(program.bits)
                    ],
                }
                for program in sorted(state.daily_programs.values(), key=lambda p: p.id)
            ],
            "weekly": [
                {
                    "program": program.id,
                    **dict(zip(WEEKDAYS, program.days, strict=True)),
                }
                for program in sorted(
                    state.weekly_programs.values(), key=lambda p: p.id
                )
            ],
        }

    async def set_daily_program(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        periods = [
            (period[ATTR_START], period[ATTR_END]) for period in call.data[ATTR_PERIODS]
        ]
        try:
            bits = intervals_to_bits(periods)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_periods",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_set_daily_program(call.data[ATTR_PROGRAM], bits)

    async def set_weekly_program(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        program_id = call.data[ATTR_PROGRAM]
        current = coordinator.state.weekly_programs.get(program_id)
        if current is None and not all(day in call.data for day in WEEKDAYS):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="weekly_program_unknown"
            )
        days = tuple(
            call.data.get(day, current.days[index] if current else 0)
            for index, day in enumerate(WEEKDAYS)
        )
        await coordinator.async_set_weekly_program(program_id, days)

    async def get_messages(call: ServiceCall) -> ServiceResponse:
        messages = _coordinator(hass, call).state.messages or []
        return {
            "messages": [
                {
                    "index": message.index,
                    "severity": message.severity.value,
                    "source": message.source,
                    "code": message.code,
                    "started_at": message.started_at.isoformat()
                    if message.started_at
                    else None,
                    "resolved_at": message.resolved_at.isoformat()
                    if message.resolved_at
                    else None,
                    "active": message.active,
                }
                for message in messages
            ]
        }

    async def get_installer_settings(call: ServiceCall) -> ServiceResponse:
        coordinator = _installer_coordinator(hass, call)
        group = InstallerSettingsGroup(call.data[ATTR_GROUP])
        settings = coordinator.state.settings.get(group)
        return {
            "fields": {
                name: {
                    "value": field.value,
                    "min": field.minimum,
                    "max": field.maximum,
                    "step": field.step,
                }
                for name, field in (settings.fields.items() if settings else ())
            }
        }

    async def set_installer_settings(call: ServiceCall) -> None:
        coordinator = _installer_coordinator(hass, call)
        await coordinator.async_set_settings(
            InstallerSettingsGroup(call.data[ATTR_GROUP]), dict(call.data[ATTR_VALUES])
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PROGRAMS,
        get_programs,
        ENTRY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_DAILY_PROGRAM, set_daily_program, SET_DAILY_PROGRAM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WEEKLY_PROGRAM,
        set_weekly_program,
        SET_WEEKLY_PROGRAM_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MESSAGES,
        get_messages,
        ENTRY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_INSTALLER_SETTINGS,
        get_installer_settings,
        GROUP_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INSTALLER_SETTINGS,
        set_installer_settings,
        SET_INSTALLER_SETTINGS_SCHEMA,
    )
