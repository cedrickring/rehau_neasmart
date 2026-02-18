# Rehau Nea Smart Home Assistant Integration

Custom integration for Rehau Nea Smart floor heating system.

## Features

- Climate entities for each zone/thermostat
- Real-time temperature updates via MQTT
- Set target temperatures
- View current temperatures and heating demand
- Automatic token refresh

## Installation

### Manual Installation

1. Copy the `custom_components/rehau_neasmart` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Configuration -> Integrations
4. Click "+ Add Integration"
5. Search for "Rehau Nea Smart"
6. Follow the setup wizard

### HACS Installation (Future)

This integration can be installed via HACS once published.

## Configuration

The integration uses a config flow for setup:

1. Enter your Rehau Nea Smart email and password
2. Enter the MFA code sent to your email
3. (Optional) Enter your Installation ID if you have multiple installations

### Finding Your Installation ID

If you have multiple installations, you can find your Installation ID by:

1. Running the standalone `main.py` script
2. Looking in the API response from `/v2/users/{email}/getDataofInstall`
3. Using the default value (it will use the first installation found)

## Usage

Once configured, the integration will create climate entities for each zone in your installation:

- `climate.rehau_<zone_name>`

For example: `climate.rehau_living_room`, `climate.rehau_bedroom`, etc.

The exact entity names depend on your configured zone names.

Each entity provides:

- **Current Temperature**: The measured temperature in the zone
- **Target Temperature**: The setpoint temperature
- **HVAC Mode**: Heat or Off (based on demand)
- **Demand**: Heating demand percentage (0-100%)

## Known Limitations

- Only heating mode is supported (no cooling)
- HVAC mode changes are not supported (always in heating mode)
- MFA must be completed during setup (cannot be changed later)
- Token refresh is automatic but may fail if the refresh token expires

## Troubleshooting

### Connection Issues

- Ensure your Rehau account credentials are correct
- Check that your Home Assistant instance can reach the internet
- Verify the MFA code is correct and entered within the time limit

### Temperature Not Updating

- Check the Home Assistant logs for MQTT connection errors
- Restart the integration from the Integrations page
- Verify your installation is online in the Rehau mobile app

### Debug Logging

To enable debug logging, add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.rehau_neasmart: debug
```

## Technical Details

### Architecture

- **Authentication**: OAuth 2.0 with PKCE flow and MFA
- **Communication**: MQTT over WebSocket to AWS IoT
- **Updates**: Real-time via MQTT subscriptions
- **Temperature Encoding**: Fahrenheit * 10 (e.g., 21°C = 698)

### API Endpoints

- `https://accounts.rehau.com` - Authentication
- `https://api.nea2aws.aws.rehau.cloud` - Installation data
- `wss://mqtt.nea2aws.aws.rehau.cloud/mqtt` - Real-time updates

## Credits

Reverse-engineered from the Rehau Nea Smart iOS mobile app.

## License

MIT License
