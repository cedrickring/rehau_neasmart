# REHAU Nea Smart 2.0 for Home Assistant

A Home Assistant integration that controls a REHAU Nea Smart 2.0 base station
over its **local web interface**. There's no cloud, no account and no add-on:
Home Assistant talks to the base station directly.

It replaces [rehau-bridge](https://github.com/manuxio/rehau-nea-smart-2-home-assistant)
(a Node.js add-on publishing over MQTT) with a native integration that offers the
same features. The device protocol is ported from that project, see [NOTICE](NOTICE).

## Requirements

- Home Assistant 2026.11 or newer.
- Network access from Home Assistant to the base station's web interface. A base
  station in access-point mode is usually at `http://192.168.0.2`, so the Home
  Assistant host needs a Wi-Fi interface joined to that network.
- **Nothing else may poll the base station at the same time.** It serves one
  client at a time. Stop rehau-bridge or any other tool before setting this up.

## Installation

HACS: add this repository as a custom repository (type *Integration*), install
**REHAU Nea Smart 2.0**, restart Home Assistant.

Manual: copy `custom_components/rehau_neasmart` into your configuration's
`custom_components` folder and restart.

Then go to **Settings → Devices & services → Add integration → REHAU Nea Smart 2.0**.

| Field | |
|---|---|
| Host | Address of the base station, e.g. `192.168.0.2`. |
| Installer code | Optional. Needed for calibration, I/O and installer settings. |

**Installer mode is global.** The base station has one installer flag for all
clients and no login session. Like rehau-bridge, the integration turns installer
mode on once and keeps it on until the integration is unloaded or Home Assistant
stops. While it is on, anyone opening the base station's web interface sees the
installer pages.

The code can't be verified during setup: the device answers the login the same
way whether the code is right or wrong.

### Options

| Option | Default | |
|---|---|---|
| Inputs and outputs | on | Polls the I/O page every 10 s. Its entities start disabled. Needs the installer code. |
| Calibration offsets | off | Shows probe offsets as editable numbers. Needs the installer code. |

## Entities

The base station is one device, and each room is a child device of it.

| Entity | Per | When |
|---|---|---|
| Climate | room | always. Off/Heat while heating, Off/Cool while cooling; presets are the REHAU modes (normal, reduced, program, program override, standby) |
| Humidity | room | the room has a humidity probe |
| Fancoil, fancoil speed, flap | room | the device shows a fancoil for the room in the current season |
| Display lock, adaptive start, open window detection | room | always (configuration) |
| Light | room | the room drives a light |
| Temperature/humidity offset | room | calibration option on |
| Outdoor temperature | base | the installation has an outdoor sensor |
| Operating mode, energy level | base | always; only the operating modes the device offers |
| Alarms, active alarms | base | always |
| Acknowledge alarms | base | always |
| Zone valve outputs, relays, digital inputs | base / U-module | I/O option on (disabled by default) |
| Analog inputs, analog output | U-module | I/O option on (disabled by default) |

## Actions

| Action | |
|---|---|
| `rehau_neasmart.get_programs` | Daily programs as periods, weekly programs as day assignments. |
| `rehau_neasmart.set_daily_program` | Replace a daily program's periods (quarter-hour boundaries). |
| `rehau_neasmart.set_weekly_program` | Assign daily programs to weekdays; days left out keep theirs. |
| `rehau_neasmart.get_messages` | The alarm log. |
| `rehau_neasmart.get_installer_settings` | Fields of one installer page with the limits the device declares. |
| `rehau_neasmart.set_installer_settings` | Change fields of one installer page. |

## How it talks to the device

- One request at a time, with `Connection: close` and at least 150 ms between
  requests. Reused keep-alive connections stall for 5–15 s, and back-to-back
  requests exhaust the device's socket table. A timed-out request is retried
  once after 400 ms. The default timeout is 5 s.
- Polling follows rehau-bridge's defaults: every room every
  clamp(5 s × rooms, 10 s, 30 s); dashboard and room list every 2 min; alarms
  every 5 min; system info every 10 min; room set-ups, programs and installer
  pages every 30 min. These numbers come from the bridge and were not measured
  for this integration.
- The device's forms are all-or-nothing. A write reads the form as the device
  serves it, changes only the requested fields, checks them against the
  `min`/`max`/`step` the device declares, and submits everything.
- Parsing matches page structure, not text, because the web interface ships in
  15 languages. Tests run against real pages from an Italian and a German fw 6.15
  base station.

## Known issues and gotchas

- **One client only.** Running rehau-bridge (or a browser left polling the web
  interface) next to this integration causes timeouts on both.
- **Which fields a form has depends on the installation.** A heating-only system
  has no cooling setpoints, a house without a mixing circuit has an empty heating
  curve page, and the PID page has one block per circuit. rehau-bridge used fixed
  field lists and would post missing fields as 0 °C or as their minimum.
  This integration never does.
- **Installer pages may not need installer mode.** On a German fw 6.15 unit the
  I/O page looked the same with installer mode off. The integration still holds
  installer mode, as the bridge did, because that hasn't been checked for every
  page and firmware.
- **The installer code can be longer than the login field allows.** The
  device's own login input has `maxlength="8"`, but codes are longer (10
  characters on the unit tested) and are posted in full.
- **The unique code is not the installer code** on that unit, although the
  bridge documents the code as the unique code's first eight characters. The
  integration only uses the last 12 hex digits of the unique code as its ID.
- Only firmware 6.15 has been seen. There is no version gating.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv --group dev -r pyproject.toml
.venv/bin/ruff format --check custom_components tests
.venv/bin/ruff check custom_components tests
.venv/bin/pytest --cov
```

`custom_components/rehau_neasmart/api/` has no Home Assistant imports and can be
extracted into a library. Tests never touch the network: device pages come from
`tests/fixtures/`, real captures with the unique code redacted.

## License

MIT, see [LICENSE](LICENSE).
