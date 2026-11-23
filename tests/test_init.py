"""Setup, unload, polling cadence and failure handling."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.loader import async_get_integration
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.rehau_neasmart.const import DOMAIN

from .api.fake_client import FakeClient
from .conftest import INSTALLER_CODE, UNIQUE_ID, setup_entry

IO_PAGE = "/installer-inputoutput.html"


def paths(client: FakeClient, method: str | None = None) -> list[str]:
    """Requested paths, without the I/O page polled every 10 s."""
    return [
        path
        for m, path, _ in client.calls
        if (method is None or m == method) and path != IO_PAGE
    ]


async def test_setup_reads_everything_once(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    assert loaded_entry.state is ConfigEntryState.LOADED
    requested = paths(mock_client)
    assert requested[0] == "/user-config-installer.html"
    assert requested.count("/room-operating.html") == 5
    assert requested.count("/room-set-up.html") == 5
    assert requested.count("/user-update-daily-program.html") == 10
    assert requested.count("/user-update-weekly-program.html") == 5
    # Installer mode is turned on once and held.
    assert ("POST", "/menu.html", {"instPart": INSTALLER_CODE}) in mock_client.calls
    assert paths(mock_client).count("/menu.html") == 1
    assert "/user-menu.html" not in paths(mock_client, "GET")


async def test_rooms_are_child_devices_of_the_base_station(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    base = device_registry.async_get_device_by_identifier(
        (DOMAIN, UNIQUE_ID), loaded_entry.entry_id
    )
    assert base is not None
    assert base.sw_version == "6.15"
    rooms = [
        device_registry.async_get_child_device_by_identifier(
            (DOMAIN, f"{UNIQUE_ID}_{zone}"), loaded_entry.entry_id
        )
        for zone in (0, 1, 3, 4, 5)
    ]
    assert [room.name for room in rooms if room] == [
        "Bathroom",
        "Living Room",
        "Hallway",
        "Office",
        "Bedroom",
    ]
    assert all(room and room.parent_device_id == base.id for room in rooms)


async def test_unload_leaves_installer_mode(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert mock_client.calls[-1] == ("GET", "/user-menu.html", None)


async def test_unload_survives_failed_logout(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: FakeClient
) -> None:
    mock_client.fail_paths.add("/user-menu.html")
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)


async def test_without_installer_code_no_installer_page_is_read(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID,
        data={"host": "192.168.0.2"},
        options=config_entry.options,
    )
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert "/menu.html" not in paths(mock_client)
    assert IO_PAGE not in [path for _, path, _ in mock_client.calls]


async def test_unreachable_device_retries_setup(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    mock_client.fail_paths.add("/user-config-installer.html")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_different_device_at_the_address_fails_setup(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    page = mock_client.pages["/user-config-installer.html"]
    mock_client.pages["/user-config-installer.html"] = page.replace(
        "aabbccdd00112233445566778899aabb", "ffffffffffffffffffffffffffffffff"
    )
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_empty_room_list_is_retried_once_then_fails(
    hass: HomeAssistant, mock_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    mock_client.pages["/room-page.html"] = "<html></html>"
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert paths(mock_client).count("/room-page.html") == 2


async def test_runtime_tick_reads_rooms_but_not_slow_pages(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
) -> None:
    mock_client.calls.clear()
    # Five rooms → 25 s per tick.
    freezer.tick(timedelta(seconds=25))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert paths(mock_client) == ["/room-operating.html"] * 5


async def test_dashboard_is_reread_after_two_minutes(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
) -> None:
    mock_client.calls.clear()
    for _ in range(5):
        freezer.tick(timedelta(seconds=25))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert paths(mock_client).count("/") == 1
    assert paths(mock_client).count("/room-page.html") == 1
    assert "/messages.html" not in paths(mock_client)


async def test_full_sync_after_thirty_minutes(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
) -> None:
    mock_client.calls.clear()
    freezer.tick(timedelta(minutes=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert paths(mock_client).count("/user-update-daily-program.html") == 10
    assert paths(mock_client).count("/advSett.html") == 1


async def test_device_outage_makes_entities_unavailable_and_recovers(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
) -> None:
    assert hass.states.get("climate.rehau_nea_smart_2_0_bathroom").state == "heat"
    mock_client.fail_paths.add("/room-operating.html")
    freezer.tick(timedelta(seconds=25))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert (
        hass.states.get("climate.rehau_nea_smart_2_0_bathroom").state
        == STATE_UNAVAILABLE
    )

    mock_client.fail_paths.clear()
    freezer.tick(timedelta(seconds=25))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("climate.rehau_nea_smart_2_0_bathroom").state == "heat"


async def test_one_failing_room_keeps_the_others(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
) -> None:
    mock_client.pages["/room-operating.html#3"] = mock_client.pages[
        "/room-operating.html#3"
    ].replace(">21.7<", ">20.1<")
    mock_client.fail_paths.add("/does-not-matter")
    freezer.tick(timedelta(seconds=25))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hallway = hass.states.get("climate.rehau_nea_smart_2_0_hallway")
    assert hallway.attributes["current_temperature"] == 20.1


async def test_room_added_on_the_device_gets_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mock_client: FakeClient,
) -> None:
    assert hass.states.get("climate.rehau_nea_smart_2_0_guest") is None
    page = mock_client.pages["/room-page.html"]
    marker = '<button type="submit"'
    first = page.index(marker)
    mock_client.pages["/room-page.html"] = (
        page[:first]
        + '<button type="submit" class="divRooms buttonRooms roomName" name="2">'
        '<div class="labelLeft" for="2">Guest</div><div class="labelRight" for="2">19.5</div>'
        "</button>" + page[first:]
    )
    mock_client.pages["/room-operating.html#2"] = (
        mock_client.pages["/room-operating.html#3"]
        .replace('value="Hallway"', 'value="Guest"')
        .replace(
            'name="zone" type="hidden" value="3"', 'name="zone" type="hidden" value="2"'
        )
    )
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("climate.rehau_nea_smart_2_0_guest") is not None


async def test_integration_ships_its_brand_icon(hass: HomeAssistant) -> None:
    """Home Assistant shows the icon from the integration's brand folder."""
    integration = await async_get_integration(hass, DOMAIN)

    assert integration.has_branding
    brand = integration.file_path / "brand"
    assert (brand / "icon.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (brand / "icon@2x.png").is_file()
