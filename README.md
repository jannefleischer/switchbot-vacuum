# SwitchBot Vacuum for Home Assistant

Custom [HACS](https://hacs.xyz/) integration for SwitchBot robot vacuums (S10, S20, S20 Pro, K10+, K10+ Pro) in Home Assistant.

## Supported models

| Model | Device type | Room cleaning | Mop / water control |
|---|---|---|---|
| Floor Cleaning Robot S10 | `WoSweeperOrigin` | ✅ | ✅ |
| Floor Cleaning Robot S20 | `W1106000` | ✅ | ✅ |
| Floor Cleaning Robot S20 Pro | `W1107000` | ✅ | ✅ |
| Mini Robot Vacuum K10+ | `WoSweeperMini` | ❌ ([why](#k10-room-cleaning--not-supported)) | ❌ |
| Mini Robot Vacuum K10+ Pro | `WoSweeperMiniPro` | ❌ | ❌ |

The S20 and S20 Pro speak the same cloud protocol as the S10 — the app routes all three
through the same device model, shadow properties and command IDs — so they get the full
S10 feature set, including per-room cleaning and mop control.

## Why this exists

SwitchBot does not provide a public API for their robot vacuums. The official SwitchBot integration in Home Assistant does not support vacuum control. This integration uses SwitchBot's internal cloud API (reverse-engineered from the mobile app) to provide full vacuum control, room-aware cleaning, and automatic room name discovery.

## Features

- **Vacuum entity** with full state reporting (cleaning, docked, paused, returning, idle)
- **Error detection** — error sensor with specific error types (stuck, water tank empty, brush tangled, etc.) and a problem binary sensor for easy automations
- **Room sensor entities** — one per room discovered from the vacuum's map
- **Room-aware cleaning** — clean specific rooms by name or ID, with full control over mode, suction, water level, passes, and order
- **Native area cleaning** — on Home Assistant 2026.8+ the vacuum's rooms map onto HA areas, so `vacuum.clean_area` and the dashboard's area picker work directly (S10 family only)
- **Mop & sweep control** — dropdowns for clean type (`sweep`, `mop`, `sweep_mop`, `first_sweep_then_mop`), water level and passes, plus the same options per room clean
- **Base station controls** — start/stop mop drying, trigger dust collection and mop wash
- **Base station tracking** — dedicated mop drying and mop washing binary sensors, plus a status sensor that distinguishes drying, washing, dust collection and water refilling
- **Map image** — the robot's own rendered map as an `image` entity, works with the stock picture card or `xiaomi-vacuum-map-card`
- **Cleaning history** (S10 family) — when each room was last vacuumed and mopped, kept across restarts
- **Automatic room discovery** — room names are read from the vacuum's map data when it changes, and at least daily
- **Low cloud load** — history and map are only fetched when something changed; see [Cloud requests](#cloud-requests)
- **Multi-device support** — if your account has multiple SwitchBot vacuums, the config flow lets you pick which one to add
- **Force refresh service** — manually re-download room data and device status on demand

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/jannefleischer/switchbot-vacuum` with category **Integration**
4. Search for "SwitchBot Vacuum" and install
5. Restart Home Assistant

### Manual

Copy `custom_components/switchbot_vacuum/` to your Home Assistant `config/custom_components/` directory and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **SwitchBot Vacuum**
3. Enter your SwitchBot account email and password
4. If multiple vacuums are found, select the one to add

You can add the integration multiple times for multiple vacuums.

## Screenshots

| Device & room entities | Clean rooms service | Room sensor detail |
|---|---|---|
| ![Device entities](screenshots/device-entities.png) | ![Clean rooms service](screenshots/clean-rooms-service.png) | ![Room sensor detail](screenshots/room-sensor-detail.png) |

## Entities

### Vacuum

The main entity (`vacuum.switchbot_vacuum`) provides:

| Feature | Description |
|---------|-------------|
| **State** | idle, cleaning, docked, paused, returning |
| **Battery** | Current battery percentage, as the `battery_level` attribute where Home Assistant still shows it. Current cores no longer have the vacuum battery feature. |
| **Fan speed** | Quiet, Standard, Strong, Max (lowercase names still accepted) |
| **Start** | Start full cleaning |
| **Stop / Pause** | Stop or pause current cleaning |
| **Return to base** | Send vacuum to charging station |
| **Locate** | Make the robot announce its position |
| **Clean area** | Clean the rooms mapped to one or more HA areas — S10 family, HA 2026.8+ ([details](#area-cleaning)) |

#### Extra attributes

The vacuum entity exposes additional attributes you can use in automations and templates:

| Attribute | Example | Description |
|-----------|---------|-------------|
| `water_level` | `1` | Current water output level (1–3) |
| `clean_type` | `sweep_mop` | Current mode: `sweep`, `mop`, `sweep_mop`, or `first_sweep_then_mop` |
| `times` | `1` | Number of cleaning passes |
| `last_clean_area` | `45` | Area of the current or most recent run (m², live progress) |
| `last_clean_time` | `30` | Cleaning time of the current or most recent run (minutes, live progress) |
| `rooms` | `{"ROOM_013": "Kitchen", ...}` | All known rooms with IDs and names |

**Reading attributes in templates:**

```yaml
# Get battery level
{{ state_attr('vacuum.switchbot_vacuum', 'battery_level') }}

# Get current clean type
{{ state_attr('vacuum.switchbot_vacuum', 'clean_type') }}

# Get last cleaned area
{{ state_attr('vacuum.switchbot_vacuum', 'last_clean_area') }} m²

# List all room names
{% for id, name in state_attr('vacuum.switchbot_vacuum', 'rooms').items() %}
  {{ name }} ({{ id }})
{% endfor %}
```

### Error & problem detection

| Entity | Type | Description |
|--------|------|-------------|
| `binary_sensor.*.problem` | Problem | ON when any error is active — simplest automation trigger |
| `sensor.*.error` | Sensor | Current error type as a string (e.g. `stuck`, `clean_water_tank_empty`) or `none` |

The error sensor reports a name drawn from the robot's own error enum. The codes group
by range — see [the API reference](docs/switchbot-vacuum-api.md) for the full table:

| Range | Meaning | Examples |
|-------|---------|----------|
| `0` | No error | `none` |
| 1001–1003 | Robot hardware | `fan_exception`, `battery_exception` |
| 2001–2048 | Robot faults | `device_stuck`, `wheel_lock`, `roller_lock`, `radar_covered`, `water_station_leak` |
| 3002–3062 | Base station and consumables | `dust_bag_full`, `sewage_slop_tank_full`, `dust_cover_open`, `roller_missing` |
| 4001–4029 | Power and scheduling | `clean_water_tank_shortage`, `low_power`, `charge_exception` |
| — | Work status is fault with no specific code | `fault` |
| `error_XXXX` | Unknown code, logged as a warning so it can be identified | |

Codes `4011`–`4015` report a *skipped* task (do-not-disturb, low power, reservation)
rather than a fault, so they do not trigger the problem binary sensor.

Both entities expose `error_code` (raw integer) and `error_type`/`error_description` as extra attributes.

> **Corrected in 0.8.0.** Earlier versions read property `1019`, which is actually
> `upgradeStatus`, so the problem sensor never fired. The old code names (`stuck`,
> `filter_clogged`, `low_battery` …) came from a different vendor's SDK and did not
> match this hardware — for example `2008` is a missing dust box, not low battery.
> If you have automations keyed on the old names, they need updating.

### Cleaning options

Three dropdowns on the device page control how the vacuum cleans (S10 family only).
They set the same clean mode the app does, and apply to `vacuum.start` and to the
vacuum card's start button:

| Entity | Options |
|--------|---------|
| `select.*.clean_type` | `sweep`, `mop`, `sweep_mop`, `first_sweep_then_mop` |
| `select.*.water_level` | `low`, `medium`, `high` |
| `select.*.passes` | `1`, `2` |

Suction is on the vacuum entity itself as the standard fan speed control.

Changing one dropdown leaves the others alone — the integration reads the current mode
and sends it back with only that field replaced, because the underlying command
replaces the whole mode object.

### Base station controls

The base station's own tasks are exposed as controls (S10 family only):

| Entity | Type | Description |
|--------|------|-------------|
| `switch.*.mop_drying` | Switch | Start and stop mop drying |
| `button.*.collect_dust` | Button | Empty the robot's bin into the station |
| `button.*.wash_mop` | Button | Run a mop wash cycle |

Dust collection and mop wash are buttons rather than switches because the API has no
command to stop them once started — only drying can be cancelled.

All three refuse to run while the station is already mid-cycle (washing, collecting
sewage, filling water or collecting dust), matching the app, which greys the buttons out
in those states. Drying and dust collection also need the robot to be on the dock.

The vacuum entity also supports `vacuum.locate`, which makes the robot announce itself.

### Base station activity

The vacuum entity reports every base station activity as `docked`, which makes drying
indistinguishable from charging. These entities keep the distinction (S10 family only):

| Entity | Type | Description |
|--------|------|-------------|
| `binary_sensor.*.mop_drying` | Binary sensor | ON while the base station is drying the mop |
| `binary_sensor.*.mop_washing` | Binary sensor | ON while the base station is washing the mop |
| `sensor.*.status` | Sensor | Raw work status name — see below |

The status sensor reports one of: `standby`, `charging`, `charge_done`, `launching`,
`wetting_mop`, `exploring`, `relocating`, `sweeping_mopping`, `sweeping`, `mopping`,
`paused`, `escaping_trap`, `fault`, `backing_to_wash_mop`, `backing_to_charge`,
`deeply_washing_mop`, `collecting_sewage`, `filling_clean_water`, `collecting_dust`,
`drying_mop`, `sleeping`, `configuring`, `remote_control`, `backing_to_base`,
`backing_to_shut_down`, `going_to_water_station`, `flushing_strainer`, `adding_water`,
`firmware_upgrading`, `scanning`, `water_station_charging`, `unknown`.

**Triggering on mop drying:**

```yaml
automation:
  - alias: "Notify when mop drying starts"
    trigger:
      - platform: state
        entity_id: binary_sensor.switchbot_vacuum_mop_drying
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "Mop drying has started"

  - alias: "Notify when mop drying finishes"
    trigger:
      - platform: state
        entity_id: binary_sensor.switchbot_vacuum_mop_drying
        from: "on"
        to: "off"
    action:
      - service: notify.mobile_app
        data:
          message: "Mop is dry"
```

### Room sensors

Each room discovered from the vacuum's map gets a sensor entity (e.g. `sensor.kitchen`, `sensor.bedroom`). The sensor value is the room name, and the `room_id` attribute contains the internal ID (e.g. `ROOM_013`).

```yaml
# Get room ID for use in clean_rooms service
{{ state_attr('sensor.kitchen', 'room_id') }}
```

### Area cleaning

Home Assistant 2026.8 added native area cleaning for vacuums, and this integration
supports it on the **S10 family only** (S10, S20, S20 Pro). The K10+ and K10+ Pro cannot
clean individual rooms through the cloud API at all, so they never advertise the feature
— see [K10+ room cleaning](#k10-room-cleaning--not-supported).

On older Home Assistant versions the feature is simply not advertised; everything else
keeps working, and `switchbot_vacuum.clean_rooms` remains the way to clean by room.

**Mapping rooms to areas**

Home Assistant owns the mapping between its areas and the vacuum's rooms, so you set it
up once:

1. Open the vacuum entity → settings (gear icon) → **Map vacuum segments to areas**
2. Pick which of the vacuum's rooms belong to each HA area (an area can hold several rooms)
3. Save

Opening the dialog re-downloads the map, so newly created or renamed rooms show up
straight away. If the vacuum later reports different rooms than the ones you mapped —
after a re-map or a room rename in the SwitchBot app — a repair notification appears
prompting you to re-map.

**Cleaning an area**

```yaml
action: vacuum.clean_area
target:
  entity_id: vacuum.switchbot_vacuum
data:
  cleaning_area_id:
    - kitchen
    - hallway
```

The clean uses the vacuum's current clean mode — the `clean_type`, `water_level` and
`passes` dropdowns plus the fan speed on the vacuum entity. Use
`switchbot_vacuum.clean_rooms` instead when you want to override those per call.

### Cleaning history (S10 family only)

The integration reads the task records the SwitchBot app shows and keeps them in Home
Assistant's storage, so they survive restarts and remain available after the cloud drops
them (up to 500 runs).

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.*_last_clean` | Timestamp | End of the last run that really cleaned |
| `sensor.*_<room>_vacuumed` | Timestamp | When this room was last vacuumed |
| `sensor.*_<room>_mopped` | Timestamp | When this room was last mopped |

The last-clean sensor exposes `start`, `rooms`, `room_ids`, `vacuumed`, `mopped`,
`clean_minutes`, `area`, `action`, `result` and `source` as attributes.

How runs are counted:

- Runs with less than one minute of cleaning time are ignored.
- A run stopped early still counts, for all rooms it was started with.
- `sweep` counts as vacuumed, `mop` as mopped, `sweep_mop` and `first_sweep_then_mop` as both.
  This reflects the mode the run was started with.
- A zone from `clean_areas` counts for the room containing its centre, once the map is loaded.
- `clean_all` counts for every known room.

### Map (S10 family only)

`image.<vacuum>_map` serves the map the robot itself renders, refreshed once a minute. Display it with the built-in picture card — no custom frontend needed:

```yaml
type: picture-entity
entity: image.s10_map
show_state: false
show_name: false
```

The entity also publishes `calibration_points`, so it works as the map source for [lovelace-xiaomi-vacuum-map-card](https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card) if you want zone selection:

```yaml
type: custom:xiaomi-vacuum-map-card
entity: vacuum.s10
map_source:
  camera: image.s10_map
calibration_source:
  camera: true
```

Vacuum coordinates are metres. See [docs/map-format.md](docs/map-format.md) for the map format.

## Services

### `switchbot_vacuum.clean_rooms`

Clean specific rooms with full control over cleaning parameters. Unlike
[`vacuum.clean_area`](#area-cleaning) this addresses the vacuum's own rooms rather than
HA areas, overrides the clean mode per call, and works on every Home Assistant version —
it is the way to clean by room before 2026.8.

```yaml
service: switchbot_vacuum.clean_rooms
target:
  entity_id: vacuum.switchbot_vacuum
data:
  rooms:
    - "Kitchen"
    - "Bedroom"
    - "ROOM_003"
  mode: "mop"
  fan_level: 2
  water_level: 2
  times: 1
  force_order: true
```

| Parameter | Required | Default | Values |
|-----------|----------|---------|--------|
| `rooms` | yes | — | List of room names or IDs (can mix) |
| `mode` | no | `sweep_mop` | `sweep`, `mop`, `sweep_mop`, `first_sweep_then_mop` |
| `fan_level` | no | `1` | 1 (quiet), 2 (standard), 3 (strong), 4 (max) |
| `water_level` | no | `1` | 1 (low), 2 (medium), 3 (high) |
| `times` | no | `1` | 1 or 2 passes |
| `force_order` | no | `true` | Clean rooms in the specified order |

### `switchbot_vacuum.set_clean_mode`

Set the sweep/mop type, suction and water level used by subsequent whole-house cleans
(`vacuum.start`). Omitted fields keep their current value. S10 family only.

```yaml
service: switchbot_vacuum.set_clean_mode
target:
  entity_id: vacuum.switchbot_vacuum
data:
  mode: "first_sweep_then_mop"
  water_level: 3
```

| Parameter | Required | Values |
|-----------|----------|--------|
| `mode` | no | `sweep`, `mop`, `sweep_mop`, `first_sweep_then_mop` |
| `fan_level` | no | 1 (quiet), 2 (standard), 3 (strong), 4 (max) |
| `water_level` | no | 1 (low), 2 (medium), 3 (high) |
| `times` | no | 1 or 2 passes |

Suction alone can also be set with the standard `vacuum.set_fan_speed` service, using
`Quiet`, `Standard`, `Strong` or `Max`. The lowercase spellings used before 0.7 are still
accepted, so existing automations keep working.

### `switchbot_vacuum.force_refresh`

Force an immediate refresh of device status and room data (re-downloads the map from S3).

```yaml
service: switchbot_vacuum.force_refresh
target:
  entity_id: vacuum.switchbot_vacuum
```

## Automation examples

### Mop the kitchen every day at 10:00

```yaml
automation:
  - alias: "Daily kitchen mop"
    trigger:
      - platform: time
        at: "10:00:00"
    action:
      - service: switchbot_vacuum.clean_rooms
        target:
          entity_id: vacuum.switchbot_vacuum
        data:
          rooms:
            - "Kitchen"
          mode: "mop"
          water_level: 2
```

### Notify when water tank is empty

```yaml
automation:
  - alias: "S10 water tank empty"
    trigger:
      - platform: state
        entity_id: sensor.floor_cleaning_robot_s10_error
        to: "clean_water_tank_empty"
    action:
      - service: notify.mobile_app
        data:
          title: "SwitchBot S10"
          message: "Clean water tank is empty — refill to continue cleaning"
```

### Notify on any problem

```yaml
automation:
  - alias: "S10 any problem"
    trigger:
      - platform: state
        entity_id: binary_sensor.floor_cleaning_robot_s10_problem
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "SwitchBot S10 problem"
          message: >
            Error: {{ state_attr('sensor.floor_cleaning_robot_s10_error', 'error_description') }}
            (code {{ state_attr('sensor.floor_cleaning_robot_s10_error', 'error_code') }})
```

### Full clean when everyone leaves

```yaml
automation:
  - alias: "Clean when away"
    trigger:
      - platform: state
        entity_id: group.family
        to: "not_home"
    action:
      - service: vacuum.start
        target:
          entity_id: vacuum.switchbot_vacuum
```

## K10+ room discovery

The K10+ does not expose room names or IDs via the public API. Room IDs are read from the cleaning schedule stored on the robot. To make room entities appear in Home Assistant you need to create at least one schedule with specific rooms selected:

1. Open the SwitchBot app
2. Go to your K10+ → **Schedule**
3. Add a new schedule, select **Clean by Room**, and pick the rooms you want
4. Save the schedule (it can be left **disabled** — it only needs to exist)

The integration reads `smartAreaIds` from all schedules every 24 hours and creates sensor entities named `room0`, `room1`, `room2`, etc. You can also trigger an immediate refresh via the `switchbot_vacuum.force_refresh` service.

Room names are not available through the API — only numeric IDs. To find which ID corresponds to which room, run the robot on a known room using the app and note which ID appears in the schedule.

## K10+ room cleaning — not supported

The K10+ **cannot** clean individual rooms via this integration, even though the SwitchBot app supports it. Here is why:

Room cleaning on the K10+ goes through **Qihoo's proprietary IoT cloud API** (`eu1-sapp-api.botslab.com`), not the standard SwitchBot API. Every request to this API requires a cryptographic `sign` query parameter. The signing algorithm is implemented inside Flutter's AOT-compiled binary (`libapp.so`) and has been extensively reverse-engineered without success:

- Over 50 combinations of MD5, SHA1, SHA256, HMAC-SHA1, and HMAC-SHA256 were tried with inputs including the app key, app secret, timestamp, nonce, auth token, cookie string, device ID, and all URL parameters — all return `{"code":1001,"msg":"Sign error"}`.
- The Dart/Flutter code is compiled to ARM64 machine code with no readable symbols, making static analysis very difficult. The signing logic is buried in 14 MB of code with no accessible source.
- The `sign_ts`, `sign_no`, `appkey`, `m2`, `appver`, `ci_brand`, `ci_model`, `ci_osver`, and `sign` parameters were all identified from APK analysis, but the exact input and order for the hash remain unknown.

Until someone intercepts a valid signed request (e.g. via SSL proxy on a rooted device) or finds the signing formula through further binary analysis, K10+ room-by-room cleaning cannot be implemented.

The `switchbot_vacuum.clean_rooms` service will **not appear** for K10+ devices. Full-house cleaning (`vacuum.start`) works normally.

## Cloud requests

The task record list cannot be queried incrementally, so the integration avoids requests
instead of asking for less data:

| Request | When |
|---------|------|
| Status | Every 30 s while the robot is active, every 5 min while it sits in the station |
| Task records | When a task starts or ends, a few follow-ups within 10 min, otherwise every 6 h |
| Map | When its metadata changes (at most every 10 min), otherwise daily; hourly retry if unavailable |

A cleaning run that starts while the robot is idle can therefore show up here up to 5
minutes late. The Bluetooth `switchbot` integration can run alongside for live status.

## Technical notes

- The integration polls the device every 30 seconds
- Auth tokens are refreshed automatically every 1.5 hours
- Room names are refreshed from S3 map data when the map changes and at least every 24 hours (or on demand via `force_refresh`); room refresh runs as a background task so it never blocks setup
- Error codes are read from device property 1019 and mapped to descriptive strings; unknown codes are logged as warnings so they can be reported and added
- Error code mappings were reverse-engineered from the SwitchBot APK's Flutter module (`feature_sweeper`, Qihoo 360 SDK)

## License

MIT
