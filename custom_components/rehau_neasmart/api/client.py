"""Single-flight HTTP client for the REHAU base station.

The firmware mishandles HTTP keep-alive: a second request on a reused TCP
connection often stalls 5-15 s before any headers come back. Every
request therefore carries `Connection: close`, which makes aiohttp drop
the connection after the response.

The device's socket table is tiny, so requests also never overlap and
start at least `min_gap` after the previous one ended.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import time
from urllib.parse import quote, urlencode

import aiohttp

from .exceptions import RehauConnectionError, RehauHttpError, RehauTimeoutError

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0
DEFAULT_MIN_GAP = 0.15
RETRY_DELAY = 0.4


@dataclass(frozen=True, slots=True)
class FetchRecord:
    """Outcome of one request, for diagnostics."""

    method: str
    path: str
    started: float
    """time.time() at the start."""
    duration: float
    outcome: str
    """ok, timeout, http or tcp."""


class RehauClient:
    """Serialized, paced HTTP access to one base station."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        min_gap: float = DEFAULT_MIN_GAP,
        on_fetch: Callable[[FetchRecord], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Create a client; `host` is a hostname or IP, optionally with a port."""
        self._session = session
        self._base_url = f"http://{host}"
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._min_gap = min_gap
        self._on_fetch = on_fetch
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_end = 0.0

    async def get(self, path: str) -> str:
        """GET a page."""
        return await self._request("GET", path, None)

    async def post_form(self, path: str, form: dict[str, str]) -> str:
        """POST an URL-encoded form."""
        return await self._request("POST", path, urlencode(form))

    async def post_key(self, path: str, key: str) -> str:
        """POST a bare `<key>=` body, the device's "open detail N" request."""
        return await self._request("POST", path, f"{quote(key, safe='')}=")

    async def _request(self, method: str, path: str, body: str | None) -> str:
        async with self._lock:
            wait = self._min_gap - (time.monotonic() - self._last_end)
            if wait > 0:
                await self._sleep(wait)
            try:
                return await self._request_with_retry(method, path, body)
            finally:
                self._last_end = time.monotonic()

    async def _request_with_retry(
        self, method: str, path: str, body: str | None
    ) -> str:
        """Send once; on a timeout wait briefly and send exactly once more.

        Every request this package makes is idempotent (reads, or
        set-to-value writes), so a retry cannot double-apply anything.
        """
        started = time.time()
        clock = time.monotonic()
        outcome = "ok"
        try:
            try:
                return await self._send(method, path, body)
            except RehauTimeoutError:
                _LOGGER.debug("%s %s timed out, retrying once", method, path)
                await self._sleep(RETRY_DELAY)
                return await self._send(method, path, body)
        except RehauTimeoutError:
            outcome = "timeout"
            raise
        except RehauHttpError:
            outcome = "http"
            raise
        except RehauConnectionError:
            outcome = "tcp"
            raise
        finally:
            self._record(method, path, started, clock, outcome)

    async def _send(self, method: str, path: str, body: str | None) -> str:
        headers = {"Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                data=body,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                text = await response.text(errors="replace")
                if not 200 <= response.status < 300:
                    raise RehauHttpError(method, path, response.status)
                return text
        except TimeoutError as err:
            raise RehauTimeoutError(f"device {method} {path} timed out") from err
        except aiohttp.ClientError as err:
            raise RehauConnectionError(f"device {method} {path} failed: {err}") from err

    def _record(
        self, method: str, path: str, started: float, clock: float, outcome: str
    ) -> None:
        if self._on_fetch is None:
            return
        self._on_fetch(
            FetchRecord(
                method=method,
                path=path,
                started=started,
                duration=time.monotonic() - clock,
                outcome=outcome,
            )
        )
