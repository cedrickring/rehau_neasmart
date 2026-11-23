"""Constants for the REHAU Nea Smart 2.0 integration."""

from datetime import timedelta
import logging

DOMAIN = "rehau_neasmart"
LOGGER = logging.getLogger(__package__)

CONF_INSTALLER_CODE = "installer_code"
CONF_EXPOSE_IO = "expose_io"
CONF_EXPOSE_CALIBRATION = "expose_calibration"

DEFAULT_EXPOSE_IO = True
DEFAULT_EXPOSE_CALIBRATION = False

# Polling cadence, taken over from rehau-bridge's defaults (config.ts), which
# ran against this device for months. They were picked by the bridge author,
# not measured here.
ROOM_SECONDS_PER_ZONE = 5
ROOM_CYCLE_MIN = timedelta(seconds=10)
ROOM_CYCLE_MAX = timedelta(seconds=30)
DASHBOARD_INTERVAL = timedelta(seconds=120)
ROOM_LIST_INTERVAL = timedelta(seconds=120)
MESSAGES_INTERVAL = timedelta(seconds=300)
SYSTEM_INFO_INTERVAL = timedelta(seconds=600)
FULL_SYNC_INTERVAL = timedelta(seconds=1800)
IO_INTERVAL = timedelta(seconds=10)

# Wait before the one boot retry of an empty room list (bridge: poller.ts).
ROOM_LIST_RETRY_DELAY = 2.0

# The device's own setpoint range per season (the RSH input's bounds).
HEATING_MIN_TEMP = 5.0
HEATING_MAX_TEMP = 31.0
COOLING_MIN_TEMP = 15.0
COOLING_MAX_TEMP = 35.0
TEMPERATURE_STEP = 0.5
