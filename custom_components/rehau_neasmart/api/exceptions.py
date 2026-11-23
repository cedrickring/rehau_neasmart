"""Errors raised by the REHAU client.

"Try again later" (connection, timeout) and "this will never work"
(HTTP status, installer access) stay separate types.
"""


class RehauError(Exception):
    """Base class for every REHAU client error."""


class RehauConnectionError(RehauError):
    """The device could not be reached (TCP error or no response)."""


class RehauTimeoutError(RehauConnectionError):
    """The device did not answer within the timeout, even after one retry."""


class RehauHttpError(RehauError):
    """The device answered with a non-2xx status."""

    def __init__(self, method: str, path: str, status: int) -> None:
        """Remember the request and status."""
        super().__init__(f"device {method} {path} returned {status}")
        self.status = status


class RehauInstallerError(RehauError):
    """An installer-only page was requested without an installer code."""


class RehauInvalidDeviceError(RehauError):
    """The host answered, but not with a recognizable REHAU Nea Smart 2.0 page."""
