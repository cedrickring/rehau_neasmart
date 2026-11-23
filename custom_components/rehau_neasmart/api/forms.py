"""Round-trip of the device's all-or-nothing HTML forms.

Which inputs a form has depends on the installation: a heating-only
system has no cooling setpoints, a house without a mixing circuit has an
empty heat-curve page, the PID page has one block per circuit. So writes
never build a form from a fixed field list. They read the form the device
served, change only the requested fields, and submit every field the way
a browser would. Number fields are checked against the `min`, `max` and
`step` the device itself declares on the input.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Literal

from bs4 import BeautifulSoup, Tag

from .codecs import celsius_to_f10

type FieldKind = Literal["hidden", "text", "number", "checkbox", "select"]


@dataclass(frozen=True, slots=True)
class FormField:
    """One named input or select of a form, in document order."""

    name: str
    kind: FieldKind
    value: str
    checked: bool = False
    element_id: str | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    step: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DeviceForm:
    """A form as served by the device."""

    action: str
    fields: tuple[FormField, ...]
    unnamed_numbers: dict[str, Decimal]
    """Number inputs that have an id but no name, such as the set-up page's
    °C inputs whose values reach the device only through `<id>H` hiddens."""

    def get(self, name: str) -> FormField | None:
        """Return the field with this name, if the form has it."""
        return next((field for field in self.fields if field.name == name), None)

    def number_by_id(self, element_id: str) -> Decimal | None:
        """Return the current value of a number input by its id."""
        for field in self.fields:
            if field.kind == "number" and field.element_id == element_id:
                return _decimal(field.value)
        return self.unnamed_numbers.get(element_id)


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def _field(element: Tag) -> FormField | None:
    name = element.get("name")
    if not isinstance(name, str) or not name:
        return None
    element_id = element.get("id")
    element_id = element_id if isinstance(element_id, str) else None
    if element.name == "select":
        options = element.find_all("option")
        chosen = next((o for o in options if o.has_attr("selected")), None)
        chosen = chosen or (options[0] if options else None)
        value = chosen.get("value", chosen.get_text()) if chosen else ""
        return FormField(
            name=name,
            kind="select",
            value=str(value),
            element_id=element_id,
        )
    input_type = str(element.get("type", "text")).lower()
    if input_type in ("submit", "button", "reset", "image", "time"):
        return None
    value = element.get("value")
    if input_type == "checkbox":
        return FormField(
            name=name,
            kind="checkbox",
            value=str(value) if isinstance(value, str) else "on",
            checked=element.has_attr("checked"),
            element_id=element_id,
        )
    kind: FieldKind = input_type if input_type in ("hidden", "number") else "text"
    return FormField(
        name=name,
        kind=kind,
        value=value if isinstance(value, str) else "",
        element_id=element_id,
        minimum=_decimal(element.get("min")),
        maximum=_decimal(element.get("max")),
        step=_decimal(element.get("step")),
    )


def parse_form(html: str, action: str) -> DeviceForm:
    """Parse the form posting to `action` (or the first form if none matches).

    Raises ValueError when the page has no form at all, e.g. when the
    device served an error or login page instead.
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", attrs={"action": action}) or soup.find("form")
    if not isinstance(form, Tag):
        raise ValueError(f"page has no form for {action}")
    fields = tuple(
        field
        for element in form.find_all(["input", "select"])
        if (field := _field(element)) is not None
    )
    unnamed = {
        str(element["id"]): number
        for element in form.find_all("input", attrs={"type": "number"})
        if not element.get("name")
        and isinstance(element.get("id"), str)
        and (number := _decimal(element.get("value"))) is not None
    }
    found_action = form.get("action")
    return DeviceForm(
        action=found_action if isinstance(found_action, str) else action,
        fields=fields,
        unnamed_numbers=unnamed,
    )


def _format(value: Decimal, step: Decimal | None) -> str:
    """Render a number with the precision of the input's step ("0.1" → one decimal)."""
    exponent = step.normalize().as_tuple().exponent if step is not None else 0
    places = max(0, -exponent) if isinstance(exponent, int) else 0
    return f"{value:.{places}f}"


def _checked_number(field: FormField, raw: float | int | str) -> str:
    try:
        number = Decimal(str(raw))
    except InvalidOperation as err:
        raise ValueError(f"{field.name}: {raw!r} is not a number") from err
    if field.minimum is not None and number < field.minimum:
        raise ValueError(f"{field.name}: {number} is below the minimum {field.minimum}")
    if field.maximum is not None and number > field.maximum:
        raise ValueError(f"{field.name}: {number} is above the maximum {field.maximum}")
    if field.step is not None and field.step > 0:
        base = field.minimum if field.minimum is not None else Decimal(0)
        if (number - base) % field.step != 0:
            raise ValueError(
                f"{field.name}: {number} is not a multiple of {field.step}"
            )
    return _format(number, field.step)


def apply_changes(
    form: DeviceForm, changes: dict[str, float | int | bool | str]
) -> DeviceForm:
    """Return the form with `changes` applied, validated against the device's limits.

    Raises ValueError for a field the form does not have, a boolean for a
    non-checkbox (or vice versa), or a number outside min/max/step.
    """
    by_name = {field.name: field for field in form.fields}
    updated: dict[str, FormField] = {}
    for name, raw in changes.items():
        field = by_name.get(name)
        if field is None:
            raise ValueError(f"the device form has no field {name}")
        if field.kind == "checkbox":
            if not isinstance(raw, bool):
                raise ValueError(f"{name} is a checkbox and needs true or false")
            updated[name] = replace(field, checked=raw)
        elif isinstance(raw, bool):
            raise ValueError(f"{name} is not a checkbox")
        elif field.kind == "number":
            updated[name] = replace(field, value=_checked_number(field, raw))
        else:
            updated[name] = replace(field, value=str(raw))
    return replace(
        form, fields=tuple(updated.get(field.name, field) for field in form.fields)
    )


def form_body(form: DeviceForm, *, fahrenheit_hidden: bool = False) -> dict[str, str]:
    """Encode the form the way a browser submits it.

    Unchecked checkboxes are left out. With `fahrenheit_hidden`, every
    hidden `<X>H` field is filled with °F×10 of input `<X>`, which is what
    the room set-up page's own `validate()` does before submitting.
    """
    body: dict[str, str] = {}
    for field in form.fields:
        if field.kind == "checkbox":
            if field.checked:
                body[field.name] = field.value
            continue
        value = field.value
        if fahrenheit_hidden and field.kind == "hidden" and field.name.endswith("H"):
            celsius = form.number_by_id(field.name[:-1])
            if celsius is not None:
                value = str(celsius_to_f10(float(celsius)))
        body[field.name] = value
    return body
