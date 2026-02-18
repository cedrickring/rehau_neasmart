# Rehau Nea Smart Testing Scripts

This folder contains standalone testing scripts for development and debugging.

## Files

### `auth_client.py`
Authentication client with OAuth 2.0 + PKCE and MFA support.

**Usage:**
```bash
python auth_client.py
```

This will:
1. Prompt for email and password
2. Send MFA code to your email
3. Prompt for the 6-digit MFA code
4. Save tokens to `rehau_tokens.json`

**Configuration:**
- Update `DEFAULT_INSTALL_ID` in the script if needed (currently set to a placeholder)
- Tokens are saved to `rehau_tokens.json` (automatically gitignored)

### `mqtt_client.py`
MQTT client for controlling thermostats.

**Usage:**
```bash
python mqtt_client.py
```

This will:
1. Load tokens from `rehau_tokens.json`
2. Fetch installation data and display all zones
3. Prompt for zone channel ID to control
4. Prompt for target temperature
5. Connect to MQTT and send temperature change command

**Features:**
- Real-time MQTT connection
- Automatic token refresh
- Temperature conversion (Celsius ↔ Fahrenheit * 10)
- Zone information display

### `test_token_refresh.py`
Test script for token refresh functionality.

**Usage:**
```bash
python test_token_refresh.py
```

This will:
1. Load existing tokens
2. Check if token is expired
3. Refresh the access token using refresh token
4. Verify the new token works with introspection

**Use Cases:**
- Test token refresh before expiration
- Verify refresh token is still valid
- Debug token refresh issues

### `test_auto_refresh.py`
Test automatic token refresh in `get_valid_token()` method.

**Usage:**
```bash
python test_auto_refresh.py
```

This will:
1. Load existing tokens
2. Simulate an expired token (set expiration to 1 minute)
3. Call `get_valid_token()` which should auto-refresh
4. Verify the token was automatically refreshed

**Use Cases:**
- Test automatic refresh logic
- Verify get_valid_token() behavior
- Debug refresh trigger conditions

## Setup

1. Install dependencies:
```bash
pip install requests websockets
```

2. Run authentication:
```bash
python auth_client.py
```

3. Test MQTT connection:
```bash
python mqtt_client.py
```

## Testing Workflow

### Initial Setup
```bash
# 1. Authenticate and get tokens
python auth_client.py

# 2. Test basic MQTT control
python mqtt_client.py
```

### Token Refresh Testing
```bash
# Test manual token refresh
python test_token_refresh.py

# Test automatic token refresh
python test_auto_refresh.py
```

### Development Cycle
```bash
# When tokens expire, refresh them
python test_token_refresh.py

# Or re-authenticate
python auth_client.py

# Continue testing MQTT
python mqtt_client.py
```

## Important Notes

⚠️ **Security:**
- Never commit `rehau_tokens.json` (contains access tokens)
- Never commit files with real email addresses
- Never commit files with installation IDs

⚠️ **Configuration:**
- Update the `DEFAULT_INSTALL_ID` constant in scripts before sharing
- Remove any hardcoded email addresses
- The current installation ID is a placeholder

## API Endpoints

- **Authentication**: `https://accounts.rehau.com`
- **Installation Data**: `https://api.nea2aws.aws.rehau.cloud/v2/users/{email}/getDataofInstall`
- **MQTT**: `wss://mqtt.nea2aws.aws.rehau.cloud/mqtt`

## MQTT Message Format

Temperature change request:
```json
{
  "11": "REQ_TH",
  "12": {
    "2": 716,    // Temperature in Fahrenheit * 10 (e.g., 71.6°F = 22°C)
    "15": 0
  },
  "35": "0",     // Always "0"
  "36": 3        // Zone number (integer)
}
```

## Temperature Encoding

- API uses Fahrenheit * 10
- Example: 21°C = 69.8°F = 698
- Conversion: `celsius_to_api_value = (celsius * 9/5 + 32) * 10`

## Zone Numbers

Zone numbers correspond to the `number` field in the zone data from the API response.

**Example zones:**
- Zone 0: First zone (e.g., "Bathroom")
- Zone 1: Second zone (e.g., "Living Room")
- Zone 3: Third zone (e.g., "Kitchen")
- Zone 4: Fourth zone (e.g., "Bedroom")

**Important Notes:**
- Zone numbers may not be sequential (e.g., 0, 1, 3, 4, 5 - skipping 2)
- Zone names are installation-specific and set by the user
- Check the API response to see your actual zone names and numbers
- Run `python mqtt_client.py` to see a list of your zones

## Troubleshooting

### Authentication Fails
- Check email and password
- Ensure MFA code is entered within time limit
- Delete `rehau_tokens.json` and re-authenticate

### MQTT Connection Fails
- Ensure token is valid (check with introspect endpoint)
- Verify iOS headers are included
- Check that session ID (sid) is used as client ID

### Temperature Not Changing
- Verify zone number is correct (not channel ID)
- Ensure field 35 is "0" (string)
- Ensure field 36 is zone number (integer)
- Check MQTT message was published successfully

## Development

For Home Assistant integration, see `custom_components/rehau_neasmart/`.

## License

MIT License
