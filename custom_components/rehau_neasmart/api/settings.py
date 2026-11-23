"""Installer settings pages.

Every page is a flat form posting to `/installer-setting.html`, told apart
by a hidden key field. Fields and their limits are read from the page
itself, because which ones exist depends on the installation.
"""

from __future__ import annotations

from .forms import DeviceForm, parse_form
from .models import InstallerSettings, InstallerSettingsGroup, SettingValue

SETTINGS_ACTION = "installer-setting.html"

SETTINGS_PAGES: dict[InstallerSettingsGroup, str] = {
    InstallerSettingsGroup.CURVE: "/circSett.html",
    InstallerSettingsGroup.HEATCOOL: "/hCSett.html",
    InstallerSettingsGroup.DEVICES: "/deviSett.html",
    InstallerSettingsGroup.FUNCTIONS: "/funcSett.html",
    InstallerSettingsGroup.PID: "/advSett.html",
    InstallerSettingsGroup.FANCOIL: "/installer-fanc-settings.html",
}


def form_values(form: DeviceForm) -> dict[str, SettingValue]:
    """Collect the number and checkbox inputs of a form with their limits."""
    fields: dict[str, SettingValue] = {}
    for field in form.fields:
        if field.kind == "checkbox":
            fields[field.name] = SettingValue(value=field.checked)
        elif field.kind == "number" and field.value:
            fields[field.name] = SettingValue(
                value=float(field.value),
                minimum=float(field.minimum) if field.minimum is not None else None,
                maximum=float(field.maximum) if field.maximum is not None else None,
                step=float(field.step) if field.step is not None else None,
            )
    return fields


def settings_from_form(
    group: InstallerSettingsGroup, form: DeviceForm
) -> InstallerSettings:
    """Collect the number and checkbox inputs of a settings form."""
    return InstallerSettings(group=group, fields=form_values(form))


def parse_settings(group: InstallerSettingsGroup, html: str) -> InstallerSettings:
    """Parse one installer settings page."""
    return settings_from_form(group, parse_form(html, SETTINGS_ACTION))
