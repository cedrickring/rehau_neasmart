"""Config, reconfigure and options flows."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.rehau_neasmart.api.exceptions import (
    RehauConnectionError,
    RehauHttpError,
)
from custom_components.rehau_neasmart.const import (
    CONF_EXPOSE_CALIBRATION,
    CONF_EXPOSE_IO,
    CONF_INSTALLER_CODE,
    DOMAIN,
)

from .api.fake_client import FakeClient
from .conftest import HOST, INSTALLER_CODE, UNIQUE_ID

pytestmark = pytest.mark.usefixtures("mock_client")


async def start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result["flow_id"]


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    flow_id = await start(hass)
    with patch("custom_components.rehau_neasmart.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_HOST: f" {HOST} ", CONF_INSTALLER_CODE: f" {INSTALLER_CODE} "},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "REHAU Nea Smart 2.0"
    assert result["data"] == {CONF_HOST: HOST, CONF_INSTALLER_CODE: INSTALLER_CODE}
    assert result["result"].unique_id == UNIQUE_ID


async def test_user_flow_without_installer_code(hass: HomeAssistant) -> None:
    flow_id = await start(hass)
    with patch("custom_components.rehau_neasmart.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_HOST: HOST}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST}


async def test_validation_does_not_touch_installer_mode(
    hass: HomeAssistant, mock_client: FakeClient
) -> None:
    flow_id = await start(hass)
    with patch("custom_components.rehau_neasmart.async_setup_entry", return_value=True):
        await hass.config_entries.flow.async_configure(
            flow_id, {CONF_HOST: HOST, CONF_INSTALLER_CODE: INSTALLER_CODE}
        )
    assert [path for _, path, _ in mock_client.calls] == [
        "/user-config-installer.html",
        "/room-page.html",
    ]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RehauConnectionError("down"), "cannot_connect"),
        (RehauHttpError("GET", "/", 404), "invalid_device"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant, error: Exception, expected: str
) -> None:
    flow_id = await start(hass)
    with patch(
        "custom_components.rehau_neasmart.config_flow.RehauDevice.fetch_system_info",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_HOST: HOST}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    with patch("custom_components.rehau_neasmart.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_HOST: HOST}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_not_a_rehau_device(
    hass: HomeAssistant, mock_client: FakeClient
) -> None:
    mock_client.pages["/user-config-installer.html"] = (
        "<html><body>router</body></html>"
    )
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_HOST: HOST})
    assert result["errors"] == {"base": "invalid_device"}


async def test_user_flow_no_rooms(hass: HomeAssistant, mock_client: FakeClient) -> None:
    mock_client.pages["/room-page.html"] = "<html></html>"
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_HOST: HOST})
    assert result["errors"] == {"base": "no_rooms"}


async def test_user_flow_installer_code_too_long(
    hass: HomeAssistant, mock_client: FakeClient
) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_HOST: HOST, CONF_INSTALLER_CODE: "123456789"}
    )
    assert result["errors"] == {CONF_INSTALLER_CODE: "installer_code_too_long"}
    assert mock_client.calls == []


async def test_already_configured_updates_host(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_HOST: "10.0.0.9"}
    )
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reconfigure(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    with patch("custom_components.rehau_neasmart.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.0.3"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_HOST: "192.168.0.3"}


async def test_reconfigure_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    mock_client.fail_paths.add("/user-config-installer.html")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_to_another_device_aborts(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    config_entry.add_to_hass(hass)
    page = mock_client.pages["/user-config-installer.html"]
    mock_client.pages["/user-config-installer.html"] = page.replace(
        "aabbccdd00112233445566778899aabb", "ffffffffffffffffffffffffffffffff"
    )
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data[CONF_INSTALLER_CODE] == INSTALLER_CODE


async def test_options_flow(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXPOSE_IO: False, CONF_EXPOSE_CALIBRATION: False}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options == {
        CONF_EXPOSE_IO: False,
        CONF_EXPOSE_CALIBRATION: False,
    }
    # Reloaded with the new options: no I/O coordinator any more.
    assert loaded_entry.runtime_data.io_coordinator is None
