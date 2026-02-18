import asyncio
import json
import struct
import sys
import uuid
from websockets import connect
import ssl

# Import from main.py
from main import RehauAuthClient


class MQTTWebSocketClient:
    def __init__(self, access_token: str, email: str, device_id: str, session_id: str):
        self.access_token = access_token
        self.email = email
        self.device_id = device_id
        self.session_id = session_id
        self.mqtt_url = "wss://mqtt.nea2aws.aws.rehau.cloud/mqtt"
        self.websocket = None
        self.packet_id = 1
        # Use session ID (sid) as client ID
        self.client_id = f"app-{session_id}"

    def _get_next_packet_id(self) -> int:
        """Get next packet ID for MQTT messages"""
        packet_id = self.packet_id
        self.packet_id += 1
        return packet_id

    def _create_mqtt_connect(self) -> bytes:
        """Create MQTT CONNECT packet with AWS custom authorizer"""
        # Use the pre-generated client ID
        client_id = self.client_id

        # Username for AWS custom authorizer
        username = f"{self.email}?x-amz-customauthorizer-name=app-front"

        # Password is the JWT access token
        password = self.access_token

        # Build MQTT CONNECT packet
        # Fixed header: 0x10 (CONNECT), remaining length will be calculated
        protocol_name = b'\x00\x04MQTT'  # Protocol name length + "MQTT"
        protocol_level = b'\x04'  # MQTT 3.1.1
        connect_flags = b'\xc2'  # Username flag + Password flag + Clean Session
        keep_alive = b'\x00<'  # 60 seconds

        # Client ID
        client_id_bytes = client_id.encode('utf-8')
        client_id_field = struct.pack('!H', len(client_id_bytes)) + client_id_bytes

        # Username
        username_bytes = username.encode('utf-8')
        username_field = struct.pack('!H', len(username_bytes)) + username_bytes

        # Password
        password_bytes = password.encode('utf-8')
        password_field = struct.pack('!H', len(password_bytes)) + password_bytes

        # Variable header + payload
        variable_header = protocol_name + protocol_level + connect_flags + keep_alive
        payload = client_id_field + username_field + password_field

        # Calculate remaining length
        remaining_length = len(variable_header) + len(payload)

        # Encode remaining length (variable length encoding)
        remaining_length_bytes = self._encode_remaining_length(remaining_length)

        # Fixed header
        fixed_header = b'\x10' + remaining_length_bytes

        return fixed_header + variable_header + payload

    def _encode_remaining_length(self, length: int) -> bytes:
        """Encode remaining length using MQTT variable length encoding"""
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

    def _create_subscribe(self, topic: str, qos: int = 0) -> bytes:
        """Create MQTT SUBSCRIBE packet"""
        packet_id = self._get_next_packet_id()

        # Topic with QoS
        topic_bytes = topic.encode('utf-8')
        topic_field = struct.pack('!H', len(topic_bytes)) + topic_bytes + bytes([qos])

        # Variable header (packet identifier)
        variable_header = struct.pack('!H', packet_id)

        # Calculate remaining length
        remaining_length = len(variable_header) + len(topic_field)
        remaining_length_bytes = self._encode_remaining_length(remaining_length)

        # Fixed header: 0x82 (SUBSCRIBE with QoS 1), 0x22 for packet type
        fixed_header = b'\x82' + remaining_length_bytes

        return fixed_header + variable_header + topic_field

    def _create_publish(self, topic: str, payload: str, qos: int = 0) -> bytes:
        """Create MQTT PUBLISH packet"""
        # Topic
        topic_bytes = topic.encode('utf-8')
        topic_field = struct.pack('!H', len(topic_bytes)) + topic_bytes

        # Payload
        payload_bytes = payload.encode('utf-8')

        # Variable header
        variable_header = topic_field

        # Calculate remaining length
        remaining_length = len(variable_header) + len(payload_bytes)
        remaining_length_bytes = self._encode_remaining_length(remaining_length)

        # Fixed header: 0x30 (PUBLISH with QoS 0, no retain, no dup)
        fixed_header = b'\x30' + remaining_length_bytes

        return fixed_header + variable_header + payload_bytes

    def _create_disconnect(self) -> bytes:
        """Create MQTT DISCONNECT packet"""
        return b'\xe0\x00'

    def celsius_to_api_value(self, celsius: float) -> int:
        """Convert Celsius to API value (Fahrenheit * 10)"""
        fahrenheit = celsius * 9/5 + 32
        return int(fahrenheit * 10)

    def api_value_to_celsius(self, value: int) -> float:
        """Convert API value to Celsius"""
        fahrenheit = value / 10
        return (fahrenheit - 32) * 5/9

    async def connect(self):
        """Connect to MQTT over WebSocket"""
        print(f"Connecting to {self.mqtt_url}...")

        # Create SSL context (disable cert verification for testing)
        ssl_context = ssl.create_default_context()

        # Connect with WebSocket subprotocol for MQTT and iOS headers
        self.websocket = await connect(
            self.mqtt_url,
            subprotocols=["mqtt"],
            ssl=ssl_context,
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
                "Sec-Fetch-Dest": "websocket"
            }
        )
        print("WebSocket connected")

        # Send MQTT CONNECT
        connect_packet = self._create_mqtt_connect()
        print(f"Debug - CONNECT packet length: {len(connect_packet)} bytes")
        print(f"Debug - CONNECT packet (first 100 bytes): {connect_packet[:100].hex()}")

        await self.websocket.send(connect_packet)
        print("MQTT CONNECT sent")

        # Wait for CONNACK with timeout
        try:
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            print(f"Debug - Received response: {response.hex() if isinstance(response, bytes) else response}")

            if len(response) >= 4 and response[0] == 0x20:
                return_code = response[3]
                if return_code == 0x00:
                    print("MQTT CONNACK received - Connection successful")
                else:
                    error_codes = {
                        0x01: "Connection refused: unacceptable protocol version",
                        0x02: "Connection refused: identifier rejected",
                        0x03: "Connection refused: server unavailable",
                        0x04: "Connection refused: bad username or password",
                        0x05: "Connection refused: not authorized"
                    }
                    error_msg = error_codes.get(return_code, f"Unknown error code: {return_code}")
                    raise Exception(f"MQTT connection failed: {error_msg}")
            else:
                print(f"Unexpected response: {response.hex()}")
                raise Exception("MQTT connection failed: unexpected response")
        except asyncio.TimeoutError:
            raise Exception("MQTT connection failed: timeout waiting for CONNACK")

    async def subscribe(self, topic: str):
        """Subscribe to a topic"""
        subscribe_packet = self._create_subscribe(topic)
        await self.websocket.send(subscribe_packet)
        print(f"Subscribed to: {topic}")

        # Wait for SUBACK
        response = await self.websocket.recv()
        print(f"SUBACK received: {response.hex()}")

    async def set_temperature(self, channel_id: str, temperature_celsius: float, zone_number: int = None):
        """Set thermostat temperature

        Args:
            channel_id: Channel ID as string (e.g., "03")
            temperature_celsius: Target temperature in Celsius
            zone_number: Zone number as integer (if None, derived from channel_id)
        """
        # Convert temperature to API value
        api_value = self.celsius_to_api_value(temperature_celsius)

        # Field 36 appears to be the zone number as integer
        if zone_number is None:
            zone_number = int(channel_id)

        print(f"\nSetting temperature to {temperature_celsius}°C (API value: {api_value}, {api_value/10}°F)")

        # Create the message payload
        message = {
            "11": "REQ_TH",
            "12": {
                "2": api_value,
                "15": 0
            },
            "35": "0",  # Always "0" in captured messages
            "36": zone_number  # Zone number as integer
        }

        payload = json.dumps(message, separators=(',', ':'))
        print(f"Message payload: {payload}")

        # Publish to device topic
        topic = f"client/{self.device_id}"
        publish_packet = self._create_publish(topic, payload)

        await self.websocket.send(publish_packet)
        print(f"Published to: {topic}")

    async def receive_messages(self, timeout: float = 5.0):
        """Receive and print incoming messages"""
        print("\nWaiting for messages...\n")
        try:
            while True:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)

                # Parse MQTT packet type
                packet_type = response[0] >> 4

                if packet_type == 3:  # PUBLISH
                    # Parse PUBLISH packet
                    remaining_length_start = 1
                    topic_length = struct.unpack('!H', response[2:4])[0]
                    topic = response[4:4+topic_length].decode('utf-8')
                    payload_start = 4 + topic_length
                    payload = response[payload_start:].decode('utf-8', errors='ignore')

                    print(f"📨 Received message on topic: {topic}")

                    # Try to parse as JSON
                    try:
                        data = json.loads(payload)
                        print(f"📄 Payload (parsed):")

                        # Extract temperature info if present
                        if isinstance(data, dict) and 'data' in data:
                            channel_data = data.get('data', {}).get('data', {})
                            if 'setpoint_h_normal' in channel_data:
                                setpoint = channel_data['setpoint_h_normal']
                                temp_celsius = self.api_value_to_celsius(setpoint)
                                print(f"   🌡️  Setpoint: {setpoint} (API) = {temp_celsius:.1f}°C")
                            if 'temp_zone' in channel_data:
                                current = channel_data['temp_zone']
                                current_celsius = self.api_value_to_celsius(current)
                                print(f"   🌡️  Current: {current} (API) = {current_celsius:.1f}°C")
                            if 'demand' in channel_data:
                                print(f"   ⚡ Demand: {channel_data['demand']}%")

                        print(f"   Full JSON: {json.dumps(data, indent=2)[:500]}...\n")
                    except json.JSONDecodeError:
                        print(f"📄 Payload (raw): {payload[:200]}...\n")
                else:
                    print(f"📦 Received packet type {packet_type}: {response.hex()}")

        except asyncio.TimeoutError:
            print("No more messages (timeout)")

    async def disconnect(self):
        """Disconnect from MQTT"""
        if self.websocket:
            try:
                disconnect_packet = self._create_disconnect()
                await self.websocket.send(disconnect_packet)
            except:
                pass  # Ignore errors if connection already closed

            try:
                await self.websocket.close()
                print("\nDisconnected")
            except:
                pass  # Ignore close errors


async def main():
    print("=== MQTT WebSocket Client for Rehau Floor Heating ===\n")

    # Initialize auth client
    auth_client = RehauAuthClient()

    # Try to get valid token (will refresh if needed)
    try:
        access_token = auth_client.get_valid_token()
        token_data = auth_client.load_tokens()
        email = input("Enter your email: ").strip()

        # Get installation data
        print("\nFetching installation data...")
        install_data = auth_client.get_install_data(email)

        # Extract installation info
        user = install_data.get("user", {})
        installs = user.get("installs", [])

        if not installs:
            print("❌ No installations found for this account")
            sys.exit(1)

        print(f"✅ Found {len(installs)} installation(s)")

        # Get device ID from first install
        install = installs[0]
        DEVICE_ID = install.get("unique")

        print(f"📱 Device ID: {DEVICE_ID}")

        # Show zones with channel IDs
        def api_value_to_celsius(value):
            """Convert API value to Celsius"""
            fahrenheit = value / 10
            return (fahrenheit - 32) * 5/9

        groups = install.get("groups", [])
        if groups and groups[0].get("zones"):
            zones = groups[0]["zones"]
            print(f"\n🏠 Found {len(zones)} zones:")
            for zone in zones:
                zone_name = zone.get('name', 'Unknown')
                channels = zone.get('channels', [])
                if channels:
                    channel = channels[0]
                    channel_id = channel.get('number', 'Unknown')
                    temp_current = channel.get('temp_zone')
                    temp_setpoint = channel.get('setpoint_used')
                    demand = channel.get('demand', 0)

                    temp_c = api_value_to_celsius(temp_current) if temp_current else 0
                    setpoint_c = api_value_to_celsius(temp_setpoint) if temp_setpoint else 0

                    print(f"   [{channel_id}] {zone_name}: {temp_c:.1f}°C → {setpoint_c:.1f}°C (demand: {demand}%)")

            # Build zone lookup for user selection
            zone_map = {}
            for zone in zones:
                channels = zone.get('channels', [])
                if channels:
                    channel = channels[0]
                    channel_id = channel.get('number', 'Unknown')
                    zone_name = zone.get('name', 'Unknown')
                    zone_map[channel_id] = zone_name

    except Exception as e:
        print(f"❌ {e}")
        print("\nPlease run 'python main.py' first to login and obtain tokens.")
        sys.exit(1)

    # Select zone to control
    print("\n" + "="*60)
    CHANNEL_ID = input("Enter channel ID to control: ").strip()

    if not CHANNEL_ID:
        print("❌ Channel ID is required")
        sys.exit(1)

    if CHANNEL_ID not in zone_map:
        print(f"⚠️  Warning: Channel {CHANNEL_ID} not found in zone list")
    else:
        print(f"Selected zone: {zone_map[CHANNEL_ID]}")

    temp_input = input("Enter target temperature in Celsius: ").strip()

    if not temp_input:
        print("❌ Temperature is required")
        sys.exit(1)

    TARGET_TEMPERATURE = float(temp_input)

    # Get session ID from tokens
    session_id = token_data.get('sid')
    if not session_id:
        print("❌ No session ID found in tokens")
        sys.exit(1)

    # Create MQTT client
    mqtt_client = MQTTWebSocketClient(access_token, email, DEVICE_ID, session_id)

    try:
        # Connect
        await mqtt_client.connect()

        # Subscribe to topics
        await mqtt_client.subscribe(f"client/{email}")
        await asyncio.sleep(0.5)

        await mqtt_client.subscribe(f"client/{DEVICE_ID}/realtime")
        await asyncio.sleep(0.5)

        # Set temperature
        await mqtt_client.set_temperature(CHANNEL_ID, TARGET_TEMPERATURE)

        # Receive response messages
        await mqtt_client.receive_messages(timeout=10.0)

    finally:
        # Disconnect
        await mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
