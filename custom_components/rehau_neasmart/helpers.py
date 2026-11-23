"""Small integration-level helpers."""

UNIQUE_ID_LENGTH = 12


def entry_unique_id(unique_code: str) -> str:
    """Derive the config entry's unique id from the device's unique code.

    Only the trailing hex digits are used: the bridge documents the leading
    eight as the installer password on some units, and unique ids end up in
    entity ids, the registry and diagnostics.
    """
    return unique_code.lower()[-UNIQUE_ID_LENGTH:]
