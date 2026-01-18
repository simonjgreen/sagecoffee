# Sage Coffee Control Library

Python library and CLI for controlling Breville/Sage coffee machines via their cloud API.

> **Security Warning**: This library handles authentication tokens that provide access to your coffee machine. Keep your tokens secure and never share them publicly. The refresh token in particular can be used to generate new access tokens indefinitely.

## Features

- OAuth authentication against Breville/Sage Auth0
- Automatic token refresh when tokens expire
- WebSocket connection for real-time state updates
- REST API for sending commands (wake, sleep, etc.)
- Appliance discovery (no need to hard-code serial numbers)
- CLI tool (`sagectl`) for command-line control
- Clean async Python API for integration into other projects

## Installation

```bash
# From source
git clone https://github.com/simonjgreen/sagecoffee.git
cd sagecoffee
pip install -e .

# With development dependencies
pip install -e ".[dev]"
```

## Quick Start

### 1. Bootstrap Authentication

First, you need to authenticate with your Breville account to obtain a refresh token:

```bash
# Bootstrap will prompt for your password (never stored)
sagectl bootstrap --username your.email@example.com
```

This stores your refresh token in `~/.config/sagecoffee/config.toml` with secure permissions (0600).

### 2. List Your Appliances

```bash
sagectl appliances
```

Output:
```
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Name                ┃ Model  ┃ Serial Number       ┃ Pairing Type ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ Oracle Dual Boiler  │ BES995 │ nnnnnnnnnnnnnnnnn   │ wifi         │
└─────────────────────┴────────┴─────────────────────┴──────────────┘
```

### 3. Control Your Machine

```bash
# Wake up the machine
sagectl wake

# Put the machine to sleep
sagectl sleep

# Wake and wait until ready (with timeout)
sagectl wake --wait --timeout 300
```

### 4. Monitor State

```bash
# Stream state updates (press Ctrl+C to stop)
sagectl tail

# Get a single state snapshot
sagectl tail --once

# Output as JSON lines (for scripting)
sagectl tail --jsonl

# Show specific fields
sagectl tail --fields state,boiler
```

## Environment Variables

All configuration can be provided via environment variables:

| Variable | Description |
|----------|-------------|
| `SAGECOFFEE_CLIENT_ID` | OAuth client ID (has default, rarely needed) |
| `SAGECOFFEE_REFRESH_TOKEN` | Refresh token (or use config file) |
| `SAGECOFFEE_SERIAL` | Appliance serial number (optional, auto-discovered) |
| `SAGECOFFEE_MODEL` | Appliance model (default: `BES995`) |
| `SAGECOFFEE_APP` | App identifier (default: `sageCoffee`) |

## Configuration File

The config file is stored at `~/.config/sagecoffee/config.toml`:

```toml
refresh_token = "your_refresh_token"
serial = "nnnnnnnnnnnnnnn"
model = "BES995"
app = "sageCoffee"
```

**Important**: The config file contains sensitive tokens. It is created with restrictive permissions (0600). The CLI will warn you if permissions are too permissive.

## Python Library Usage

### Basic Usage

```python
import asyncio
from sagecoffee import SageCoffeeClient

async def main():
    async with SageCoffeeClient(
        client_id="your_client_id",
        refresh_token="your_refresh_token",
    ) as client:
        # List appliances
        appliances = await client.list_appliances()
        print(f"Found {len(appliances)} appliances")
        
        # Wake up the machine
        await client.wake()
        
        # Stream state updates
        async for state in client.tail_state():
            print(f"State: {state.reported_state}")
            if state.reported_state == "ready":
                break

asyncio.run(main())
```

### Using ConfigStore

```python
from sagecoffee import SageCoffeeClient
from sagecoffee.store import ConfigStore

async def main():
    store = ConfigStore()
    async with SageCoffeeClient.from_config(store) as client:
        await client.wake()
```

### Low-Level API Access

```python
from sagecoffee.auth import AuthClient
from sagecoffee.http_api import BrevilleApiClient
from sagecoffee.ws_client import BrevilleWsClient

# Direct auth client usage
auth = AuthClient(client_id="...")
tokens = await auth.password_realm_login(username, password)
tokens = await auth.refresh(tokens.refresh_token)

# Direct HTTP API usage
api = BrevilleApiClient(get_id_token=lambda: tokens.id_token)
await api.wake("SERIAL123")

# Direct WebSocket usage
ws = BrevilleWsClient(get_id_token=lambda: tokens.id_token)
await ws.connect()
await ws.add_appliance("SERIAL123")
async for state in ws.listen_states():
    print(state.reported_state)
```

## Token Refresh Logic

The library automatically handles token refresh:

1. **Expiry Detection**: Tokens are checked against their JWT `exp` claim, with a configurable skew (default 60 seconds before expiry).

2. **Automatic Refresh**: When a token is near expiry:
   - The `TokenManager` refreshes it using the stored refresh_token
   - An asyncio lock prevents concurrent refresh stampedes
   - The new refresh_token is persisted if it was rotated

3. **401 Handling**: If an API call returns 401:
   - The token is refreshed
   - The request is retried once

4. **WebSocket Reconnection**: If the WebSocket disconnects:
   - Exponential backoff with jitter
   - Token refresh before reconnect if near expiry
   - Automatic re-registration of appliances

## State Model

The `DeviceState` object provides convenient access to appliance state:

```python
state.reported_state      # "asleep", "warming", "ready", etc.
state.desired_state       # What state was requested
state.boiler_temps        # List of BoilerState objects
state.grind_size          # Grinder setting
state.is_remote_wake_enabled  # Whether remote wake is allowed
state.timezone            # Configured timezone
state.raw_data            # Full raw state dict
```

## Machine Configuration Defaults

Default settings discovered from a BES995 (Oracle Dual Boiler):

| Setting | Default | Notes |
|---------|---------|-------|
| Grind size | 19 | Range ~1-45 |
| Brew temp | 93.3°C | Boiler ID 1 |
| Steam temp | 131°C | Boiler ID 0 |
| Volume | 50 | 0-100 |
| Display brightness | 50 | 0-100 |
| Work light brightness | 100 | Cup warmer light, 0-100 |
| Auto-off time | 20 min | Idle time before sleep |
| Temp unit | 0 | 0=Celsius, 1=Fahrenheit |
| Theme | `"dark"` | Display theme |
| Timezone | `"Europe/London"` | Machine timezone |
| Wake schedule | `20 6 * * 1-5` | 6:20 AM weekdays (cron format) |

### State Report Structure

The WebSocket returns state reports with this structure:

```json
{
  "serialNumber": "nnnnnnnnnnnnnnnn",
  "messageType": "stateReport",
  "data": {
    "desired": { "REQUESTID": "None", "REQUEST": "None" },
    "reported": {
      "state": "ready",
      "cfg": {
        "default": {
          "work_light_brightness": 100,
          "brightness": 50,
          "theme": "dark",
          "vol": 50,
          "idle_time": 20,
          "wake_schedule": [{"cron": "20 6 * * 1-5", "on": true}],
          "temp_unit": 0,
          "timezone": "Europe/London"
        }
      },
      "grind": { "size_setting": 19 },
      "boiler": [
        { "id": 0, "temp_sp": 131, "cur_temp": 100 },
        { "id": 1, "temp_sp": 93.3, "cur_temp": 93.3 }
      ],
      "firmware": { "mcu0": "1.0.13", "appVersion": "1.1.20" }
    }
  }
}
```

## CLI Commands Reference

| Command | Description |
|---------|-------------|
| `sagectl bootstrap` | Authenticate and store refresh token |
| `sagectl refresh` | Manually refresh tokens |
| `sagectl appliances` | List discovered appliances |
| `sagectl tail` | Stream state updates |
| `sagectl wake` | Wake up appliance |
| `sagectl sleep` | Put appliance to sleep |
| `sagectl config` | Show configuration |
| `sagectl raw ws '...'` | Send raw WebSocket message |
| `sagectl raw http METHOD /path '...'` | Send raw HTTP request |

### Common Options

- `--serial`, `-s`: Specify appliance serial number
- `--debug`: Enable debug logging (with redacted secrets)
- `--wait`, `-w`: Wait for state transition (wake/sleep)
- `--timeout`, `-t`: Timeout for wait operations
- `--jsonl`: Output as JSON lines
- `--once`: Exit after first state report

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Authentication failure |
| 2 | Configuration missing |
| 3 | Network failure |
| 4 | Timeout waiting for state |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=sagecoffee

# Type checking
mypy src/sagecoffee

# Linting
ruff check src/sagecoffee

# Formatting
black src/sagecoffee tests
```

## Security Considerations

1. **Never commit tokens**: Add `config.toml` to your `.gitignore`
2. **Use environment variables in CI**: Don't store tokens in code
3. **Restrictive file permissions**: The library enforces 0600 on config files
4. **Token redaction**: Debug logs automatically redact sensitive values
5. **No password storage**: The bootstrap command never stores your password

## Known Endpoints

The library uses these Breville/Sage cloud endpoints:

- **OAuth**: `https://my.breville.com/oauth/token`
- **REST API**: `https://iot-api.breville.com/appliance/v1/...`
- **User API**: `https://iot-api.breville.com/user/v2/...`
- **WebSocket**: `wss://iot-api-ws.breville.com/applianceProxy`

## License

MIT License - see LICENSE file for details.

## Disclaimer

This is an unofficial library. It is not affiliated with, endorsed by, or supported by Breville or Sage. Use at your own risk.
