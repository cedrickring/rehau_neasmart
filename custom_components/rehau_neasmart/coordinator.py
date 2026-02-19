"""Data coordinator for Rehau Nea Smart."""
import asyncio
import json
import logging
import ssl
import struct
from functools import partial
from typing import Any, Callable

from websockets import connect

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import RehauAuthClient

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = 30  # seconds


class RehauDataCoordinator(DataUpdateCoordinator):
    """Coordinate data updates from Rehau MQTT."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth_client: RehauAuthClient,
        email: str,
        device_id: str,
        install_data: dict[str, Any],
    ):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Rehau Nea Smart",
            update_interval=None,  # We'll update via MQTT messages
        )
        self.auth_client = auth_client
        self.email = email
        self.device_id = device_id
        self.install_data = install_data
        self.websocket = None
        self.packet_id = 1
        self._update_callbacks: list[Callable] = []
        self._running = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3

    def celsius_to_api_value(self, celsius: float) -> int:
        """Convert Celsius to API value (Fahrenheit * 10)."""
        fahrenheit = celsius * 9 / 5 + 32
        return int(fahrenheit * 10)

    def api_value_to_celsius(self, value: int) -> float:
        """Convert API value to Celsius."""
        fahrenheit = value / 10
        return (fahrenheit - 32) * 5 / 9

    def _get_next_packet_id(self) -> int:
        """Get next packet ID for MQTT messages."""
        packet_id = self.packet_id
        self.packet_id += 1
        return packet_id

    def _encode_remaining_length(self, length: int) -> bytes:
        """Encode remaining length using MQTT variable length encoding."""
        result = bytearray()
        while True:
            byte = length % 128
            length = length // 128
            if length > 0:
                byte |= 0x80
            result.append(byte)
            if length == 0:
                break
        return bytes(result)

    def _create_mqtt_connect(self) -> bytes:
        """Create MQTT CONNECT packet."""
        client_id = f"app-{self.auth_client.sid}"
        username = f"{self.email}?x-amz-customauthorizer-name=app-front"
        password = self.auth_client.access_token

        # Build MQTT CONNECT packet
        protocol_name = b"\x00\x04MQTT"
        protocol_level = b"\x04"
        connect_flags = b"\xc2"
        keep_alive = b"\x00<"

        client_id_bytes = client_id.encode("utf-8")
        client_id_field = struct.pack("!H", len(client_id_bytes)) + client_id_bytes

        username_bytes = username.encode("utf-8")
        username_field = struct.pack("!H", len(username_bytes)) + username_bytes

        password_bytes = password.encode("utf-8")
        password_field = struct.pack("!H", len(password_bytes)) + password_bytes

        variable_header = protocol_name + protocol_level + connect_flags + keep_alive
        payload = client_id_field + username_field + password_field

        remaining_length = len(variable_header) + len(payload)
        remaining_length_bytes = self._encode_remaining_length(remaining_length)

        return b"\x10" + remaining_length_bytes + variable_header + payload

    def _create_subscribe(self, topic: str, qos: int = 0) -> bytes:
        """Create MQTT SUBSCRIBE packet."""
        packet_id = self._get_next_packet_id()

        topic_bytes = topic.encode("utf-8")
        topic_field = struct.pack("!H", len(topic_bytes)) + topic_bytes + bytes([qos])

        variable_header = struct.pack("!H", packet_id)

        remaining_length = len(variable_header) + len(topic_field)
        remaining_length_bytes = self._encode_remaining_length(remaining_length)

        return b"\x82" + remaining_length_bytes + variable_header + topic_field

    def _create_publish(self, topic: str, payload: str, qos: int = 0) -> bytes:
        """Create MQTT PUBLISH packet."""
        topic_bytes = topic.encode("utf-8")
        topic_field = struct.pack("!H", len(topic_bytes)) + topic_bytes

        payload_bytes = payload.encode("utf-8")

        remaining_length = len(topic_field) + len(payload_bytes)
        remaining_length_bytes = self._encode_remaining_length(remaining_length)

        return b"\x30" + remaining_length_bytes + topic_field + payload_bytes

    async def connect_mqtt(self, retry_with_refresh: bool = True):
        """Connect to MQTT over WebSocket."""
        _LOGGER.debug("Connecting to MQTT broker")
        mqtt_url = "wss://mqtt.nea2aws.aws.rehau.cloud/mqtt"

        # Fix blocking call: run ssl.create_default_context() in executor
        ssl_context = await self.hass.async_add_executor_job(ssl.create_default_context)

        self.websocket = await connect(
            mqtt_url,
            subprotocols=["mqtt"],
            ssl=ssl_context,
            ping_interval=None,  # Disable websocket ping, use MQTT keepalive
            ping_timeout=None,
            additional_headers={
                "Origin": "app://ios.neasmart.de",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "websocket",
                "Sec-Fetch-Dest": "websocket",
            },
        )
        _LOGGER.debug("WebSocket connection established")

        # Send MQTT CONNECT
        _LOGGER.debug(f"Sending MQTT CONNECT with client_id: app-{self.auth_client.sid}")
        connect_packet = self._create_mqtt_connect()
        await self.websocket.send(connect_packet)

        # Wait for CONNACK
        try:
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            if len(response) >= 4 and response[0] == 0x20:
                return_code = response[3]
                if return_code == 0x00:
                    _LOGGER.info("MQTT connection established successfully")
                    self._reconnect_attempts = 0  # Reset on success
                elif return_code in [0x04, 0x05] and retry_with_refresh:
                    # 0x04 = Bad username or password, 0x05 = Not authorized
                    _LOGGER.warning(f"MQTT auth failed (code {return_code}), attempting token refresh")
                    try:
                        await self.auth_client.refresh_access_token()
                        await self._update_config_entry_tokens()
                        _LOGGER.info("Token refreshed, retrying MQTT connection")
                        # Close current websocket and retry once without refresh
                        await self.websocket.close()
                        self.websocket = None
                        return await self.connect_mqtt(retry_with_refresh=False)
                    except Exception as e:
                        raise UpdateFailed(f"Token refresh failed: {e}")
                else:
                    raise UpdateFailed(f"MQTT connection refused with code: {return_code}")
            else:
                raise UpdateFailed("Unexpected MQTT response")
        except asyncio.TimeoutError:
            raise UpdateFailed("MQTT connection timeout")

        # Subscribe to topics
        _LOGGER.debug(f"Subscribing to topic: client/{self.email}")
        await self.websocket.send(self._create_subscribe(f"client/{self.email}"))
        await self.websocket.recv()  # SUBACK

        _LOGGER.debug(f"Subscribing to topic: client/{self.device_id}/realtime")
        await self.websocket.send(self._create_subscribe(f"client/{self.device_id}/realtime"))
        await self.websocket.recv()  # SUBACK

        # Start message listener
        _LOGGER.info("Starting MQTT message listener")
        self._running = True
        asyncio.create_task(self._listen_messages())

        # Start keepalive task (send PINGREQ every 30 seconds)
        asyncio.create_task(self._keepalive())

    async def _update_config_entry_tokens(self):
        """Update config entry with refreshed tokens."""
        from datetime import datetime
        from homeassistant.config_entries import ConfigEntry
        from .const import DOMAIN

        # Find the config entry for this coordinator
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if self.hass.data.get(DOMAIN, {}).get(entry.entry_id) == self:
                new_data = dict(entry.data)
                new_data["access_token"] = self.auth_client.access_token
                new_data["refresh_token"] = self.auth_client.refresh_token
                new_data["sid"] = self.auth_client.sid
                new_data["expires_at"] = self.auth_client.expires_at.isoformat() if self.auth_client.expires_at else None
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.debug("Updated config entry with new tokens")
                break

    async def _keepalive(self):
        """Send MQTT PINGREQ packets to keep connection alive."""
        while self._running and self.websocket:
            try:
                await asyncio.sleep(30)  # Keep alive interval (matches 60s timeout with margin)
                if self.websocket and self._running:
                    # MQTT PINGREQ packet
                    pingreq = b'\xc0\x00'
                    await self.websocket.send(pingreq)
                    _LOGGER.debug("Sent MQTT PINGREQ")
            except Exception as e:
                _LOGGER.error(f"Error sending keepalive: {e}")
                await self._attempt_reconnect_with_refresh()
                break

    async def _listen_messages(self):
        """Listen for incoming MQTT messages."""
        while self._running and self.websocket:
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=60.0)

                # Parse MQTT packet
                packet_type = response[0] >> 4

                if packet_type == 3:  # PUBLISH
                    topic_length = struct.unpack("!H", response[2:4])[0]
                    topic = response[4 : 4 + topic_length].decode("utf-8")
                    payload_start = 4 + topic_length
                    payload = response[payload_start:].decode("utf-8", errors="ignore")

                    try:
                        data = json.loads(payload)
                        _LOGGER.debug(f"Received MQTT message: {data}")

                        # Update coordinator data
                        await self._handle_message(data)

                    except json.JSONDecodeError:
                        _LOGGER.warning(f"Failed to parse message payload: {payload[:100]}")
                
                elif packet_type == 13:  # PINGRESP
                    _LOGGER.debug("Received MQTT PINGRESP")

            except asyncio.TimeoutError:
                _LOGGER.warning("MQTT receive timeout, connection might be dead")
                await self._attempt_reconnect_with_refresh()
                break
            except Exception as e:
                _LOGGER.error(f"Error listening to MQTT: {e}")
                await self._attempt_reconnect_with_refresh()
                break

    async def _attempt_reconnect_with_refresh(self):
        """Attempt to reconnect to MQTT, refreshing token if needed."""
        self._running = False

        if self._reconnect_attempts >= self._max_reconnect_attempts:
            _LOGGER.error(f"Max reconnection attempts ({self._max_reconnect_attempts}) reached, giving up")
            return

        self._reconnect_attempts += 1
        _LOGGER.info(f"Attempting reconnection {self._reconnect_attempts}/{self._max_reconnect_attempts}")

        try:
            # Close existing connection
            if self.websocket:
                await self.websocket.close()
                self.websocket = None

            # Try refreshing token before reconnecting
            try:
                await self.auth_client.refresh_access_token()
                await self._update_config_entry_tokens()
                _LOGGER.info("Token refreshed before reconnection attempt")
            except Exception as e:
                _LOGGER.warning(f"Token refresh failed during reconnection: {e}")

            # Wait before reconnecting
            await asyncio.sleep(5 * self._reconnect_attempts)

            # Attempt to reconnect
            await self.connect_mqtt()
            _LOGGER.info("Successfully reconnected to MQTT")

        except Exception as e:
            _LOGGER.error(f"Reconnection attempt failed: {e}")
            # Schedule another reconnection attempt
            await asyncio.sleep(10)
            if self._reconnect_attempts < self._max_reconnect_attempts:
                await self._attempt_reconnect_with_refresh()

    async def _handle_message(self, data: dict):
        """Handle incoming MQTT message."""
        # Update internal data structure with new zone information
        # Trigger callbacks to update entities
        self.async_set_updated_data(data)

    def _is_websocket_connected(self) -> bool:
        """Check if websocket is connected and open."""
        if not self.websocket:
            return False
        # Check if websocket is in open state
        try:
            from websockets.protocol import State
            return self.websocket.protocol.state == State.OPEN
        except Exception:
            return False

    async def _send_zone_command(self, zone_number: int, params: dict, retry: bool = True):
        """Send a command to a zone via MQTT."""
        if not self._is_websocket_connected():
            if retry:
                _LOGGER.warning("Websocket disconnected, attempting reconnection before sending command")
                try:
                    await self._attempt_reconnect_with_refresh()
                    await asyncio.sleep(1)
                    return await self._send_zone_command(zone_number, params, retry=False)
                except Exception as e:
                    raise UpdateFailed(f"Failed to reconnect before sending command: {e}")
            else:
                raise UpdateFailed("Not connected to MQTT and reconnection failed")

        message = {
            "11": "REQ_TH",
            "12": params,
            "35": "0",
            "36": zone_number,
        }

        payload = json.dumps(message, separators=(",", ":"))
        topic = f"client/{self.device_id}"

        try:
            _LOGGER.debug(f"Publishing MQTT message: {payload}")
            publish_packet = self._create_publish(topic, payload)
            await self.websocket.send(publish_packet)
            _LOGGER.info(f"Command sent for zone {zone_number}: {params}")
        except Exception as e:
            if retry:
                _LOGGER.warning(f"Failed to send command: {e}, attempting reconnection")
                await self._attempt_reconnect_with_refresh()
                await asyncio.sleep(1)
                return await self._send_zone_command(zone_number, params, retry=False)
            else:
                raise UpdateFailed(f"Failed to send command: {e}")

    async def set_temperature(self, zone_number: int, temperature_celsius: float):
        """Set zone temperature."""
        api_value = self.celsius_to_api_value(temperature_celsius)
        _LOGGER.debug(f"Setting temperature for zone {zone_number} to {temperature_celsius}°C (API value: {api_value})")
        await self._send_zone_command(zone_number, {"2": api_value, "15": 0})

    async def set_operation_mode(self, zone_number: int, mode: int):
        """Set zone operation mode.

        Mode values:
        0 = PRESENCE (manual/comfort)
        1 = ABSENCE (eco/away)
        2 = OFF
        4 = AUTO (timing programs/schedule)
        """
        _LOGGER.debug(f"Setting operation mode for zone {zone_number} to {mode}")
        await self._send_zone_command(zone_number, {"15": mode})

    async def set_light_ring(self, zone_number: int, enabled: bool):
        """Enable or disable light ring on zone controller.

        Args:
            zone_number: The zone number
            enabled: True to enable, False to disable
        """
        value = 1 if enabled else 0
        _LOGGER.debug(f"Setting light ring for zone {zone_number} to {enabled}")
        await self._send_zone_command(zone_number, {"34": value})

    async def disconnect(self):
        """Disconnect from MQTT."""
        _LOGGER.debug("Disconnecting from MQTT")
        self._running = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            _LOGGER.info("MQTT connection closed")

    async def _async_update_data(self):
        """Fetch data from API (fallback if MQTT is down)."""
        try:
            install_data = await self.auth_client.get_install_data(self.email, self.install_data.get("install_id"))
            return install_data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
