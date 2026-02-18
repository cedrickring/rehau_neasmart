# Rehau Nea Smart Floor Heating Control - Project Summary

This project provides Home Assistant integration and standalone testing scripts for controlling Rehau Nea Smart floor heating systems.

## Project Structure

```
.
├── custom_components/
│   └── rehau_neasmart/          # Home Assistant custom integration
│       ├── __init__.py
│       ├── auth.py
│       ├── climate.py
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── manifest.json
│       ├── README.md
│       └── translations/
│           └── en.json
│
├── testing/                      # Standalone testing scripts (no secrets)
│   ├── auth_client.py           # Authentication client
│   ├── mqtt_client.py           # MQTT control client
│   ├── mqtt_test_sid.py         # Connection testing
│   ├── .env.example             # Environment variables template
│   ├── .gitignore               # Ignore secrets and tokens
│   └── README.md
│
└── PROJECT_SUMMARY.md           # This file
```

## Components

### Home Assistant Integration

Location: `custom_components/rehau_neasmart/`

A production-ready Home Assistant custom integration that provides:

- **Climate entities** for each thermostat zone
- **Config flow** for easy setup via UI
- **Real-time MQTT updates** for temperature and demand
- **Automatic token management** with refresh
- **Multi-factor authentication** support

**Installation:**
1. Copy the `custom_components/rehau_neasmart` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via UI (Settings → Devices & Services)
4. Enter credentials and MFA code

### Testing Scripts

Location: `testing/`

Standalone Python scripts for development and debugging (no personal data):

1. **auth_client.py** - OAuth 2.0 authentication with PKCE and MFA
2. **mqtt_client.py** - MQTT client for controlling zones
3. **mqtt_test_sid.py** - Test different MQTT authentication methods

**Usage:**
```bash
cd testing
python auth_client.py  # Login and save tokens
python mqtt_client.py  # Control thermostats
```

## Technical Details

### Authentication Flow

1. OAuth 2.0 authorization with PKCE
2. Username/password login
3. MFA code via email (6 digits)
4. Token exchange (access + refresh tokens)
5. Token introspection before MQTT

### MQTT Communication

- **Protocol**: MQTT over WebSocket (wss://)
- **Broker**: AWS IoT Core at `mqtt.nea2aws.aws.rehau.cloud`
- **Authentication**: Custom authorizer with JWT token
- **Client ID Format**: `app-{session_id}`
- **Username Format**: `{email}?x-amz-customauthorizer-name=app-front`

### Temperature Control Message

```json
{
  "11": "REQ_TH",
  "12": {
    "2": 716,    // Temperature (Fahrenheit * 10)
    "15": 0
  },
  "35": "0",     // Always "0"
  "36": 3        // Zone number (integer)
}
```

### Temperature Encoding

- API uses: **Fahrenheit × 10**
- Example: 21°C = 69.8°F = **698**
- Conversion: `(celsius * 9/5 + 32) * 10`

### Key Discovery: iOS Headers Required

The MQTT connection **only works** with exact iOS app headers:

```python
{
    "Origin": "app://ios.neasmart.de",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7...)",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "websocket",
    "Sec-Fetch-Dest": "websocket"
}
```

### Key Discovery: Client ID Must Be Session ID

- Client ID must be `app-{sid}` where `sid` is from the OAuth token
- Cannot use UUID or other identifiers
- Must match the session ID from authentication

### Key Discovery: Zone Number vs Channel ID

- Field `35` is always `"0"` (string)
- Field `36` is the **zone number** (integer), not the channel ID
- Zone numbers may not be sequential (e.g., 0, 1, 3, 4, 5)

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `https://accounts.rehau.com` | Authentication |
| `https://api.nea2aws.aws.rehau.cloud/v2/users/{email}/getDataofInstall` | Installation data |
| `wss://mqtt.nea2aws.aws.rehau.cloud/mqtt` | MQTT communication |

## Security Notes

⚠️ **Important:**
- Never commit `rehau_tokens.json` (contains access tokens)
- Never commit `.env` files with credentials
- Use `.env.example` as template
- The `testing/` folder is sanitized with no personal data

## Development Process

This integration was reverse-engineered by:

1. Capturing iOS app traffic with network proxy
2. Analyzing HTTP requests and WebSocket frames
3. Decoding MQTT binary protocol
4. Testing different authentication combinations
5. Identifying critical iOS headers requirement
6. Discovering temperature encoding format
7. Understanding zone number vs channel ID distinction

## Known Limitations

- Only heating mode supported (no cooling)
- MFA required for every fresh login
- Cannot change HVAC modes (always heating)
- Token refresh may fail if refresh token expires
- Installation ID must be provided or uses first installation

## Future Improvements

- [ ] Support multiple installations
- [ ] Add preset modes (comfort, eco, away)
- [ ] Support scheduling via Home Assistant
- [ ] Add sensors for heating demand
- [ ] Better error handling for MFA
- [ ] Support for cooling mode (if available)

## Credits

Reverse-engineered from Rehau Nea Smart iOS mobile app.

## License

MIT License
