"""Edge cases of the generic form round-trip."""

import pytest

from custom_components.rehau_neasmart.api.forms import (
    apply_changes,
    form_body,
    parse_form,
)

PAGE = """<html><body>
<form action="other.html"><input name="decoy" value="x"></form>
<form action="target.html">
  <input name="key" type="hidden">
  <input name="curve" type="number" value="0.60" min="0" max="5" step="0.01">
  <input name="whole" type="number" value="3" min="1" max="9" step="1">
  <select name="pick"><option value="7">a</option><option value="8">b</option></select>
  <input name="flag" type="checkbox">
  <input name="label" type="text" value="Bad &amp; WC">
  <input type="number" id="Lonely" value="21.5">
  <input name="LonelyH" type="hidden">
  <input type="submit" value="OK">
  <input name="start" type="time">
</form></body></html>"""


def test_picks_the_form_by_action() -> None:
    form = parse_form(PAGE, "target.html")
    assert form.action == "target.html"
    assert [field.name for field in form.fields] == [
        "key",
        "curve",
        "whole",
        "pick",
        "flag",
        "label",
        "LonelyH",
    ]


def test_body_mirrors_a_browser_submission() -> None:
    body = form_body(parse_form(PAGE, "target.html"))
    assert body == {
        "key": "",
        "curve": "0.60",
        "whole": "3",
        "pick": "7",
        "label": "Bad & WC",
        "LonelyH": "",
    }


def test_fahrenheit_hidden_uses_unnamed_input_by_id() -> None:
    body = form_body(parse_form(PAGE, "target.html"), fahrenheit_hidden=True)
    assert body["LonelyH"] == "707"


def test_numbers_keep_the_step_precision() -> None:
    form = apply_changes(parse_form(PAGE, "target.html"), {"curve": 1.2, "whole": 4})
    body = form_body(form)
    assert (body["curve"], body["whole"]) == ("1.20", "4")


def test_checkbox_and_select_changes() -> None:
    form = apply_changes(parse_form(PAGE, "target.html"), {"flag": True, "pick": "8"})
    body = form_body(form)
    assert (body["flag"], body["pick"]) == ("on", "8")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"curve": 5.01}, "maximum"),
        ({"whole": 0}, "minimum"),
        ({"curve": 0.605}, "multiple"),
        ({"whole": "many"}, "not a number"),
        ({"flag": 1}, "checkbox"),
        ({"whole": True}, "not a checkbox"),
        ({"missing": 1}, "no field"),
    ],
)
def test_rejects_invalid_changes(changes: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        apply_changes(parse_form(PAGE, "target.html"), changes)


def test_page_without_form_raises() -> None:
    with pytest.raises(ValueError):
        parse_form("<html><body>login</body></html>", "target.html")
