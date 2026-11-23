"""In-memory stand-in for RehauClient that serves fixture pages."""

import asyncio
from dataclasses import dataclass, field

from pytest_homeassistant.common import load_fixture

from custom_components.rehau_neasmart.api.exceptions import RehauConnectionError


@dataclass
class FakeClient:
    """Serves pages by (path, key) and records every request."""

    pages: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, str] | str | None]] = field(
        default_factory=list
    )
    fail_paths: set[str] = field(default_factory=set)
    held: dict[str, asyncio.Event] = field(default_factory=dict)
    """POSTs to these paths wait until the event is set."""
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    """Set when a held POST starts waiting."""

    def serve(self, path: str, fixture: str, key: str | None = None) -> None:
        self.pages[f"{path}#{key}" if key is not None else path] = load_fixture(fixture)

    def _page(self, path: str, key: str | None = None) -> str:
        if path in self.fail_paths:
            raise RehauConnectionError(f"{path} unreachable")
        lookup = f"{path}#{key}" if key is not None else path
        return self.pages.get(lookup, "<html><body></body></html>")

    async def get(self, path: str) -> str:
        self.calls.append(("GET", path, None))
        return self._page(path)

    async def post_form(self, path: str, form: dict[str, str]) -> str:
        self.calls.append(("POST", path, dict(form)))
        if (release := self.held.get(path)) is not None:
            self.entered.set()
            await release.wait()
        return self._page(path)

    async def post_key(self, path: str, key: str) -> str:
        self.calls.append(("KEY", path, key))
        return self._page(path, key)


def german_device_client() -> FakeClient:
    """Serve the fw-6.15 German captures of the five-room heating-only house."""
    client = FakeClient()
    base = "fw-6.15-de"
    client.serve("/", f"{base}/dashboard.html")
    client.serve("/room-page.html", f"{base}/room-page.html")
    client.serve("/messages.html", f"{base}/messages.html")
    client.serve("/user-config-installer.html", f"{base}/user-config-installer.html")
    for zone in (0, 1, 3, 4, 5):
        client.serve(
            "/room-operating.html", f"{base}/room-operating-{zone}.html", str(zone)
        )
        client.serve("/room-set-up.html", f"{base}/room-set-up-{zone}.html", str(zone))
    for program in (1, 2, 10):
        client.serve(
            "/user-update-daily-program.html",
            f"{base}/daily-program-{program}.html",
            str(program),
        )
    # Only some programs were captured; the others reuse a capture with the
    # id the device would put in it.
    empty_daily = load_fixture(f"{base}/daily-program-10.html")
    for program in range(3, 10):
        client.pages[f"/user-update-daily-program.html#{program}"] = (
            empty_daily.replace(
                'name="idProgDay" type="hidden" value="9"',
                f'name="idProgDay" type="hidden" value="{program - 1}"',
            )
        )
    for program in (1, 5):
        client.serve(
            "/user-update-weekly-program.html",
            f"{base}/weekly-program-{program}.html",
            str(program),
        )
    weekly = load_fixture(f"{base}/weekly-program-1.html")
    for program in (2, 3, 4):
        client.pages[f"/user-update-weekly-program.html#{program}"] = weekly.replace(
            'name="weeklyProgram" type="hidden" value="1"',
            f'name="weeklyProgram" type="hidden" value="{program}"',
        )
    for page in (
        "installer-adjustementOffset",
        "installer-inputoutput",
        "installer-system-statistics",
        "diagSett",
        "circSett",
        "hCSett",
        "deviSett",
        "funcSett",
        "advSett",
        "installer-fanc-settings",
    ):
        client.serve(f"/{page}.html", f"{base}/{page}.html")
    return client
