# Rehau Nea Smart Home Assistant Integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Compatible-41BDF5.svg)](https://www.home-assistant.io/)

Custom Home Assistant integration for controlling Rehau Nea Smart floor heating systems.

## Features

- 🌡️ **Climate entities** for each thermostat zone
- 🔄 **Real-time updates** via MQTT over WebSocket
- 🎛️ **Temperature control** from Home Assistant
- 🔐 **Secure authentication** with OAuth 2.0 + PKCE + MFA
- ⚡ **Automatic token refresh** - no manual re-authentication needed
- 📊 **Heating demand monitoring** for each zone

## Screenshots

> Add screenshots of the integration in Home Assistant here

## Installation

### HACS (Recommended - Future)

This integration will be available via HACS once published to the HACS default repository.

### Manual Installation

1. Download or clone this repository
2. Copy the `custom_components/rehau_neasmart` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Go to **Settings** → **Devices & Services** → **Add Integration**
5. Search for **Rehau Nea Smart**
6. Follow the setup wizard

## Configuration

### Setup via UI (Config Flow)

1. Click **Add Integration** in Home Assistant
2. Search for "Rehau Nea Smart"
3. Enter your Rehau account credentials:
   - Email address
   - Password
   - (Optional) Installation ID - leave blank to use first installation
4. Enter the 6-digit MFA code sent to your email
5. Click **Submit**

The integration will:
- Authenticate with Rehau servers
- Fetch your installation data
- Connect to MQTT for real-time updates
- Create climate entities for each zone

### Finding Your Installation ID (Optional)

If you have multiple installations and want to specify which one to use:

1. Run the testing script: `python testing/auth_client.py`
2. Look for the installation ID in the response
3. Use that ID during setup

If not specified, the integration will automatically use your first installation.

## Usage

### Climate Entities

Each thermostat zone will appear as a climate entity with the format:

- `climate.rehau_<zone_name>`

For example:
- `climate.rehau_living_room`
- `climate.rehau_bedroom`
- `climate.rehau_kitchen`

The exact entities depend on your installation's zone names.

### Entity Attributes

Each entity provides:

| Attribute | Description |
|-----------|-------------|
| **Current Temperature** | Measured temperature in the zone |
| **Target Temperature** | Setpoint temperature |
| **HVAC Mode** | Heat or Off (based on demand) |
| **Demand** | Heating demand percentage (0-100%) |
| **Zone Number** | Internal zone identifier |
| **Min/Max Temperature** | Configured temperature limits |

### Setting Temperature

Use the thermostat card or service call:

```yaml
service: climate.set_temperature
target:
  entity_id: climate.rehau_<your_zone_name>
data:
  temperature: 21.5
```

Replace `<your_zone_name>` with your actual zone name (e.g., `living_room`).

### Automations Example

```yaml
automation:
  - alias: "Lower temperature at night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.rehau_your_zone_name
        data:
          temperature: 18
```

Replace `your_zone_name` with your actual zone name.

## Development & Testing

### Standalone Testing Scripts

The `testing/` folder contains standalone Python scripts for development:

```bash
cd testing

# Install dependencies
pip install requests websockets

# Authenticate and save tokens
python auth_client.py

# Control thermostats via MQTT
python mqtt_client.py
```

See `testing/README.md` for detailed documentation.

## Technical Details

### Architecture

- **Protocol**: MQTT over WebSocket (wss://)
- **Authentication**: OAuth 2.0 with PKCE and email-based MFA
- **Communication**: Real-time via AWS IoT MQTT broker
- **Temperature Encoding**: Fahrenheit × 10 (e.g., 21°C = 698)

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `https://accounts.rehau.com` | OAuth authentication |
| `https://api.nea2aws.aws.rehau.cloud` | Installation data |
| `wss://mqtt.nea2aws.aws.rehau.cloud/mqtt` | Real-time MQTT |

### Requirements

- Home Assistant 2023.1 or newer
- Active Rehau Nea Smart account
- Internet connection for cloud communication

## Troubleshooting

### Connection Issues

**Problem**: "Failed to connect to Rehau servers"

**Solutions**:
- Verify your credentials are correct
- Ensure your Home Assistant can reach the internet
- Check if Rehau services are operational

### MFA Issues

**Problem**: "Invalid MFA code"

**Solutions**:
- Ensure you enter the code within the time limit
- Check your email spam folder
- Request a new code and try again

### Temperature Not Updating

**Problem**: Zone temperature doesn't update

**Solutions**:
- Check Home Assistant logs for MQTT errors
- Restart the integration
- Verify your installation is online in the Rehau mobile app

### Debug Logging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.rehau_neasmart: debug
```

## Known Limitations

- Only heating mode is supported (no cooling)
- HVAC mode changes are not supported (always in heating mode)
- Token refresh requires active internet connection
- MFA code must be entered during initial setup

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Clone the repository
git clone https://github.com/cedrickring/rehau-neasmart-ha.git
cd rehau-neasmart-ha

# Install development dependencies
pip install -r requirements-dev.txt

# Run tests (when available)
pytest
```

## Support

- **Issues**: [GitHub Issues](https://github.com/cedrickring/rehau-neasmart-ha/issues)
- **Discussions**: [GitHub Discussions](https://github.com/cedrickring/rehau-neasmart-ha/discussions)
- **Home Assistant Community**: [Community Forum Thread](https://community.home-assistant.io/)

## Disclaimer

This is an unofficial integration reverse-engineered from the Rehau Nea Smart iOS mobile app. It is not affiliated with, endorsed by, or supported by REHAU.

Use at your own risk. The author is not responsible for any damage to your heating system or account.

## Credits

- Reverse-engineered by analyzing the Rehau Nea Smart iOS mobile app
- Built with ❤️ for the Home Assistant community

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### Version 0.1.0 (Initial Release)

- Initial release with basic climate entity support
- OAuth 2.0 authentication with MFA
- Real-time MQTT updates
- Temperature control for all zones
- Config flow for easy setup
