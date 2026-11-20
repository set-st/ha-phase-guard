"""Offline scenario tests for phase_guard.sensor using minimal Home Assistant stubs.

Run:  python tests/test_logic.py   (no Home Assistant installation needed)
"""
import sys, types, importlib.util, os
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- HA stubs
def mod(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m

class SensorEntity:
    _attr_native_value = None
    @property
    def native_value(self): return self._attr_native_value
class RestoreEntity:
    async def async_get_last_state(self): return None
class SensorDeviceClass: ENUM = "enum"
def callback(f): return f
NOW = [datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)]

mod("homeassistant"); mod("homeassistant.components"); mod("homeassistant.helpers"); mod("homeassistant.util")
mod("homeassistant.components.sensor", SensorEntity=SensorEntity, SensorDeviceClass=SensorDeviceClass)
mod("homeassistant.config_entries", ConfigEntry=object)
mod("homeassistant.const", STATE_UNAVAILABLE="unavailable", STATE_UNKNOWN="unknown")
mod("homeassistant.core", Event=object, HomeAssistant=object, State=object, callback=callback)
mod("homeassistant.helpers.device_registry", DeviceInfo=dict)
mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
mod("homeassistant.helpers.event", async_track_state_change_event=None, async_track_time_interval=None)
mod("homeassistant.helpers.restore_state", RestoreEntity=RestoreEntity)
mod("homeassistant.util.dt", utcnow=lambda: NOW[0])
sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]

PKG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "custom_components", "phase_guard")
pkg = types.ModuleType("phase_guard"); pkg.__path__ = [PKG]; sys.modules["phase_guard"] = pkg
for name in ("const", "sensor"):
    spec = importlib.util.spec_from_file_location(f"phase_guard.{name}", os.path.join(PKG, f"{name}.py"))
    m = importlib.util.module_from_spec(spec); sys.modules[f"phase_guard.{name}"] = m; spec.loader.exec_module(m)
S = sys.modules["phase_guard.sensor"]

class St:
    def __init__(self, state, attrs=None, ts=None):
        self.state = state; self.attributes = attrs or {}; self.last_updated = ts or NOW[0]; self.last_reported = self.last_updated
class States(dict):
    def get(self, k): return dict.get(self, k)
class Bus:
    def __init__(self): self.events = []
    def async_fire(self, n, d): self.events.append(d)
class Hass:
    def __init__(self): self.states = States(); self.bus = Bus()
class Entry: entry_id = "e1"; title = "Test"

V = {"device_class": "voltage", "unit_of_measurement": "V"}
def make():
    hass = Hass()
    cfg = {"input_min_voltage": 150, "indicator_min_voltage": 150, "input_max_age": 30, "debounce": 10}
    p = S.PhaseSensor(Entry(), 1, "sensor.input_l1_voltage", ["sensor.after_relay_voltage", "switch.after_relay_device"], cfg)
    p.hass = hass; p.async_write_ha_state = lambda: None
    o = S.OverallSensor(Entry(), [p]); o.hass = hass; o.async_write_ha_state = lambda: None
    p.listeners.append(o.async_phase_changed)
    return hass, p, o

def step(hass, p, secs, meter=None, meter_fresh=True, relay_side=None, device=None):
    NOW[0] += timedelta(seconds=secs)
    if meter is not None:
        old = hass.states.get("sensor.input_l1_voltage")
        ts = NOW[0] if meter_fresh or old is None else old.last_reported
        hass.states["sensor.input_l1_voltage"] = St(str(meter), V, ts)
    if relay_side is not None: hass.states["sensor.after_relay_voltage"] = St(str(relay_side), V)
    if device is not None: hass.states["switch.after_relay_device"] = St(device)
    p._evaluate()
    return p.native_value


def run(hass, p, secs, meter_alive=True, meter=230, relay_side=None, device=None, relay_side_lag=0):
    """Advance in 5 s ticks. The meter pushes every tick while alive; the relay-side voltage indicator may lag."""
    out = []
    for i in range(int(secs // 5)):
        NOW[0] += timedelta(seconds=5)
        if meter_alive:
            hass.states["sensor.input_l1_voltage"] = St(str(meter), V, NOW[0])
        if relay_side is not None and (i + 1) * 5 > relay_side_lag:
            hass.states["sensor.after_relay_voltage"] = St(str(relay_side), V)
        if device is not None:
            hass.states["switch.after_relay_device"] = St(device)
        p._evaluate(); out.append(p.native_value)
    return out

fails = 0
def check(name, got, want):
    global fails
    ok = got == want; fails += not ok
    print(f"  {'OK ' if ok else 'FAIL'} {name}: {got!r} (want {want!r})")

def fresh():
    hass, p, o = make()
    run(hass, p, 30, meter=236, relay_side=236, device="on")
    return hass, p, o

print("1) Protection relay trip: meter keeps reporting, downstream dies (relay-side voltage reported after 15 s)")
hass, p, o = fresh()
seq = run(hass, p, 60, meter=224, relay_side=0, device="unavailable", relay_side_lag=15)
check("final", seq[-1], "protection_trip")
check("never classified as outage", "grid_outage" in seq, False)
check("overall", o.native_value, "protection_trip")
check("max voltage before", p._stats["last_voltage_max_before"], 236.0)
check("Meter Wi-Fi gap during trip keeps trip", run(hass, p, 120, meter_alive=False)[-1], "protection_trip")
check("recovery", run(hass, p, 10, meter=225, relay_side=200, device="on")[-1], "normal")
check("counts", (p._stats["protection_trip_count"], p._stats["grid_outage_count"]), (1, 0))
check("events", [e["stage"] for e in hass.bus.events], ["start", "end"])

print("2) Real outage: meter loses power, relay-side voltage reports 0 after 15 s")
hass, p, o = fresh()
seq = run(hass, p, 60, meter_alive=False, relay_side=0, device="unavailable", relay_side_lag=15)
check("final", seq[-1], "grid_outage")
check("never classified as trip", "protection_trip" in seq, False)
check("grid back but the relay holds 10 min -> stays outage", run(hass, p, 600, meter=230, relay_side=0, device="unavailable")[-1], "grid_outage")
check("recovery", run(hass, p, 10, meter=230, relay_side=230, device="on")[-1], "normal")
check("counts", (p._stats["protection_trip_count"], p._stats["grid_outage_count"]), (0, 1))

print("3) Real outage detected only by slow availability indicator (no voltage indicator)")
hass, p, o = make()
p._indicators = ["switch.after_relay_device"]
run(hass, p, 30, meter=230, device="on")
run(hass, p, 45, meter_alive=False, device="on")
seq = run(hass, p, 60, meter_alive=False, device="unavailable")
check("final", seq[-1], "grid_outage"); check("never trip", "protection_trip" in seq, False)

print("4) Blip shorter than debounce ignored")
hass, p, o = fresh()
run(hass, p, 5, meter=230, relay_side=0, device="unavailable")
check("recovered", run(hass, p, 5, meter=230, relay_side=230, device="on")[-1], "normal")
check("no events", hass.bus.events, [])

print("5) Meter silent, downstream fine -> normal")
hass, p, o = fresh()
check("normal", run(hass, p, 300, meter_alive=False)[-1], "normal")

print("6) Only switch indicator flaky, voltage indicator alive -> normal")
hass, p, o = fresh()
check("normal", run(hass, p, 120, meter=230, device="unavailable")[-1], "normal")

print("7) Trip, then the input itself really drops to 0 V -> outage")
hass, p, o = fresh()
run(hass, p, 30, meter=230, relay_side=0, device="unavailable")
check("trip", p.native_value, "protection_trip")
check("outage", run(hass, p, 10, meter=0)[-1], "grid_outage")

print("8) No input sensor configured -> no_power")
hass, p, o = make(); p._input = None
run(hass, p, 10, meter_alive=False, relay_side=230, device="on")
check("no_power", run(hass, p, 30, meter_alive=False, relay_side=0, device="unavailable")[-1], "no_power")

print("FAILED" if fails else "ALL PASSED", fails)
sys.exit(1 if fails else 0)
