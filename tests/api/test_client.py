"""RehauClient tests against a loopback aiohttp server."""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
import time

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.rehau_neasmart.api.client import FetchRecord, RehauClient
from custom_components.rehau_neasmart.api.exceptions import (
    RehauConnectionError,
    RehauHttpError,
    RehauTimeoutError,
)

# Loopback only: the HA test plugin keeps connections limited to 127.0.0.1.
pytestmark = pytest.mark.usefixtures("socket_enabled")


@dataclass
class FakeDevice:
    """Records requests; behaviour per path is set by tests."""

    requests: list[tuple[str, str, str, str]] = field(default_factory=list)
    starts: list[float] = field(default_factory=list)
    ends: list[float] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0
    stall_first: int = 0
    status: int = 200

    async def handle(self, request: web.Request) -> web.Response:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.starts.append(time.monotonic())
        try:
            body = await request.text()
            self.requests.append(
                (
                    request.method,
                    request.path,
                    body,
                    request.headers.get("Connection", ""),
                )
            )
            if self.stall_first > 0:
                self.stall_first -= 1
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(0.01)
            return web.Response(text=f"ok {request.path}", status=self.status)
        finally:
            self.in_flight -= 1
            self.ends.append(time.monotonic())


@pytest.fixture
async def device() -> AsyncIterator[tuple[FakeDevice, str]]:
    fake = FakeDevice()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    yield fake, f"127.0.0.1:{server.port}"
    await server.close()


@pytest.fixture
async def session() -> AsyncIterator[ClientSession]:
    async with ClientSession() as client_session:
        yield client_session


def make_client(
    session: ClientSession,
    host: str,
    records: list[FetchRecord] | None = None,
    **kwargs: float,
) -> RehauClient:
    on_fetch: Callable[[FetchRecord], None] | None = (
        records.append if records is not None else None
    )
    return RehauClient(session, host, on_fetch=on_fetch, **kwargs)


async def test_get_sends_connection_close(device, session) -> None:
    fake, host = device
    assert await make_client(session, host).get("/") == "ok /"
    assert fake.requests == [("GET", "/", "", "close")]


async def test_post_form_is_url_encoded(device, session) -> None:
    fake, host = device
    await make_client(session, host).post_form(
        "/room-page.html", {"zone": "2", "RoomName": "Bad & Wc", "RSH": "20.5"}
    )
    method, path, body, _ = fake.requests[0]
    assert (method, path) == ("POST", "/room-page.html")
    assert body == "zone=2&RoomName=Bad+%26+Wc&RSH=20.5"


async def test_post_key_sends_bare_key(device, session) -> None:
    fake, host = device
    await make_client(session, host).post_key("/room-operating.html", "3")
    assert fake.requests[0][2] == "3="


async def test_concurrent_requests_never_overlap(device, session) -> None:
    fake, host = device
    client = make_client(session, host, min_gap=0)
    await asyncio.gather(*(client.get(f"/{index}") for index in range(5)))
    assert fake.max_in_flight == 1
    assert len(fake.requests) == 5


async def test_requests_keep_minimum_gap(device, session) -> None:
    fake, host = device
    client = make_client(session, host, min_gap=0.1)
    await asyncio.gather(client.get("/a"), client.get("/b"), client.get("/c"))
    gaps = [start - end for start, end in zip(fake.starts[1:], fake.ends, strict=False)]
    assert all(gap >= 0.09 for gap in gaps), gaps


async def test_retries_once_after_timeout(device, session) -> None:
    fake, host = device
    fake.stall_first = 1
    records: list[FetchRecord] = []
    client = make_client(session, host, records, timeout=0.2)
    assert await client.get("/slow") == "ok /slow"
    assert len(fake.requests) == 2
    assert [record.outcome for record in records] == ["ok"]


async def test_gives_up_after_second_timeout(device, session) -> None:
    fake, host = device
    fake.stall_first = 2
    records: list[FetchRecord] = []
    client = make_client(session, host, records, timeout=0.2)
    with pytest.raises(RehauTimeoutError):
        await client.get("/slow")
    assert len(fake.requests) == 2
    assert [record.outcome for record in records] == ["timeout"]


async def test_http_error_is_not_retried(device, session) -> None:
    fake, host = device
    fake.status = 503
    records: list[FetchRecord] = []
    with pytest.raises(RehauHttpError) as err:
        await make_client(session, host, records).get("/")
    assert err.value.status == 503
    assert len(fake.requests) == 1
    assert records[0].outcome == "http"


async def test_unreachable_device_is_connection_error(session) -> None:
    records: list[FetchRecord] = []
    # Port 9 (discard) on loopback is closed on any normal machine.
    client = make_client(session, "127.0.0.1:9", records)
    with pytest.raises(RehauConnectionError) as err:
        await client.get("/")
    assert not isinstance(err.value, RehauTimeoutError)
    assert records[0].outcome == "tcp"


async def test_failed_request_does_not_block_the_next(device, session) -> None:
    fake, host = device
    fake.status = 500
    client = make_client(session, host)
    with pytest.raises(RehauHttpError):
        await client.get("/")
    fake.status = 200
    assert await client.get("/") == "ok /"
