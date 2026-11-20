<p align="center">
  <img src="custom_components/phase_guard/brand/icon@2x.png" alt="Phase Guard" width="128">
</p>

<h1 align="center">Phase Guard</h1>

<p align="center">
  <b>Was it a grid outage — or did your phase protection relay trip?</b><br>
  A Home Assistant integration that tells the two apart, per phase.
</p>

<p align="center">
  <a href="README.uk.md">Українська</a> · English
</p>

---

## Why

Many homes protect each phase with a **voltage monitoring relay** (overvoltage / undervoltage / phase-imbalance relay). When the grid voltage swings, the relay cuts the phase off and reconnects it later. From inside the house this looks exactly like a power outage — lights go out, devices drop off Wi-Fi — but the cause and the right reaction are different:

| What happened | Grid | What you may want to do |
|---|---|---|
| **Grid outage** | gone | start the generator, switch to battery, wait for the utility |
| **Protection tripped** | still there | check voltage quality, imbalance, the relay settings |

Phase Guard compares, for each phase, the voltage **at the house input** (measured *before* the relay) with signs of life **after** the relay, and classifies what is going on.

## How it works

For every phase you choose:

- **Input** — a voltage sensor of an energy meter installed *upstream* of the protection relay (e.g. a 3-phase Wi-Fi/MQTT meter at the service entrance).
- **Indicators** — one or more entities *downstream* of the relay on that phase:
  - voltage sensors (an inverter's grid-input voltage, a smart plug that reports voltage, …) — alive while the voltage is above a threshold;
  - **any** device that becomes `unavailable` when it loses power (a Wi-Fi switch, a smart plug, a bulb…) — alive while it is available.

| Input meter | Indicators after the relay | Result |
|---|---|---|
| any | at least one alive | **Normal** |
| keeps reporting voltage **after** the phase died | all dead | **Protection tripped** |
| went silent / reports ~0 V | all dead | **Grid outage** |
| not configured | all dead | **No power** (cause unknown) |

The key rule: a **protection trip** is only declared when the input meter sends a fresh reading **after** the downstream side went dead — proof that the meter (and therefore the grid before the relay) is still alive. In a real outage the meter itself loses power and never reports again, so the event is classified as a **grid outage** even if a fast indicator noticed the loss before the meter's data went stale.

Other details:

- **Debounce** — a phase must stay dead for N seconds before an event is counted; short blips are ignored.
- **Stable classification** — a trip stays a trip during a short meter data gap; an outage stays an outage while the relay waits to reconnect after the grid returns (most relays have a reconnect delay).
- **Several indicators per phase** — the phase is dead only when *all* of them are dead, so one device dropping off Wi-Fi does not raise a false alarm.

## Requirements

- Home Assistant **2024.12** or newer (the brand icon shows up in the UI starting with 2026.3).
- An energy meter with **per-phase voltage** installed **before** the protection relays, which **loses power during a grid outage** (most mains-powered meters do). If your meter has its own backup power, outages will only be recognised when it reports ~0 V.
- At least one indicator on each phase you want to monitor.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/set-st/ha-phase-guard`, category **Integration**.
2. Find **Phase Guard** and install it.
3. Restart Home Assistant.

### Manual

1. Copy `custom_components/phase_guard` into `<config>/custom_components/`.
2. Restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → Phase Guard.**

| Field | Default | Meaning |
|---|---|---|
| Name | Phase Guard | Device name; you can create several instances (e.g. house and garage). |
| Phase N — input voltage | — | Voltage sensor of the meter *before* the relay. |
| Phase N — indicators | — | Entities *after* the relay on that phase. Leave empty to skip the phase. |
| Input: minimum voltage | 150 V | Input readings at or above this mean "grid present". |
| Indicators: minimum voltage | 150 V | Only for voltage-sensor indicators. |
| Input data timeout | 30 s | No input update for longer than this → input data is missing. |
| Debounce | 10 s | How long a phase must stay dead before an event is registered. |

Everything can be changed later via **Configure** on the integration — no YAML.

**Tips for choosing indicators**

- Prefer a **voltage sensor** that updates often (inverter grid input, a smart plug with voltage measurement): it reacts in seconds.
- Devices that only go `unavailable` usually need 30–60 s to be marked so; event times on such phases lag accordingly.
- Use **two different devices** per phase if you can — ideally on different integrations or networks.
- Pick indicators that are **not** on a UPS or inverter backup — otherwise they will never lose power.

## Entities

For each configured phase, plus one overall sensor:

| Entity | States |
|---|---|
| `sensor.<name>_phase_1` … `_phase_3` | `normal`, `protection_trip`, `grid_outage`, `no_power` |
| `sensor.<name>_input_status` | worst state across phases; attributes `phase_1` … `phase_3` |

Phase sensor attributes:

| Attribute | Description |
|---|---|
| `input_status` | `present`, `absent`, `nodata`, or `none` (not configured) |
| `indicators` | each indicator → `alive` / `dead` / `unknown` |
| `protection_trip_count`, `grid_outage_count`, `no_power_count` | counters (kept across restarts) |
| `last_event_type`, `last_event_start`, `last_event_end`, `last_event_duration_s` | the last event |
| `last_voltage_before`, `last_voltage_min_before`, `last_voltage_max_before` | input voltage right before the event and its min/max over the previous 2 minutes — handy for finding the relay's real thresholds |

State names are translated (English, Українська, Русский).

## Event

`phase_guard_event` is fired when an event starts and when it ends:

```yaml
# stage: start
entry: Phase Guard
phase: 2
type: protection_trip        # protection_trip | grid_outage | no_power
stage: start
start: "2026-11-20T12:19:24+00:00"
voltage_before: 251.3
voltage_min_before: 236.8
voltage_max_before: 252.0

# stage: end
entry: Phase Guard
phase: 2
type: protection_trip
stage: end
start: "2026-11-20T12:19:24+00:00"
end: "2026-11-20T12:21:39+00:00"
duration_s: 135
```

## Examples

### Notify when a protection relay trips

```yaml
automation:
  - alias: "Phase protection tripped"
    triggers:
      - trigger: event
        event_type: phase_guard_event
        event_data:
          type: protection_trip
          stage: start
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "Phase {{ trigger.event.data.phase }}: protection tripped"
          message: >
            Grid is present, the relay cut the phase.
            Input voltage before the trip: {{ trigger.event.data.voltage_before }} V
            (min {{ trigger.event.data.voltage_min_before }} /
            max {{ trigger.event.data.voltage_max_before }} V over 2 min).
```

### Different reactions to an outage and to a trip

```yaml
automation:
  - alias: "House input status changed"
    triggers:
      - trigger: state
        entity_id: sensor.phase_guard_input_status
    actions:
      - choose:
          - conditions: "{{ trigger.to_state.state == 'grid_outage' }}"
            sequence:
              - action: switch.turn_off
                target:
                  entity_id: switch.water_heater        # shed heavy loads
              - action: notify.mobile_app_my_phone
                data:
                  message: "Grid outage — running on backup."
          - conditions: "{{ trigger.to_state.state == 'protection_trip' }}"
            sequence:
              - action: notify.mobile_app_my_phone
                data:
                  message: "Voltage relay tripped, the grid itself is fine."
          - conditions: "{{ trigger.to_state.state == 'normal' and trigger.from_state.state not in ['unknown', 'unavailable'] }}"
            sequence:
              - action: notify.mobile_app_my_phone
                data:
                  message: "Power restored."
```

### Log every event with its duration

```yaml
automation:
  - alias: "Phase Guard log"
    triggers:
      - trigger: event
        event_type: phase_guard_event
        event_data:
          stage: end
    actions:
      - action: logbook.log
        data:
          name: "Phase {{ trigger.event.data.phase }}"
          message: >
            {{ trigger.event.data.type | replace('_', ' ') }},
            {{ trigger.event.data.duration_s }} s
```

### Dashboard

```yaml
type: entities
title: House input
entities:
  - entity: sensor.phase_guard_input_status
  - entity: sensor.phase_guard_phase_1
    secondary_info: last-changed
  - entity: sensor.phase_guard_phase_2
    secondary_info: last-changed
  - entity: sensor.phase_guard_phase_3
    secondary_info: last-changed
  - type: attribute
    entity: sensor.phase_guard_phase_1
    attribute: protection_trip_count
    name: Trips on phase 1
```

## Limitations

- An outage can only be recognised if the input meter loses power (or reports ~0 V) during it.
- If **all** indicators of a phase lose Wi-Fi at the same time while the meter is fine, it is reported as a protection trip — use different kinds of indicators to avoid this.
- The event start time is when the indicators *noticed* the loss, so it may lag behind the real moment by the indicators' reporting delay.

## Development

The classification logic can be tested without Home Assistant:

```bash
python tests/test_logic.py
```

Brand icons are generated by `tools/make_icon.py` (requires Pillow).

## License

[MIT](LICENSE)
