"""Phase Guard sensors.

Per phase: compare the house-input voltage (measured upstream of the phase
protection relay) with downstream indicators (voltage sensors, or any device that
goes unavailable when it loses power) and classify the phase as:

  normal           downstream alive
  protection_trip  downstream dead, input voltage present  -> relay cut the phase
  grid_outage      downstream dead, input absent / no fresh data
  no_power         downstream dead, no input sensor configured (cause unknown)
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEBOUNCE,
    CONF_INDICATOR_MIN_V,
    CONF_INPUT_MAX_AGE,
    CONF_INPUT_MIN_V,
    DEFAULT_DEBOUNCE,
    DEFAULT_INDICATOR_MIN_V,
    DEFAULT_INPUT_MAX_AGE,
    DEFAULT_INPUT_MIN_V,
    DOMAIN,
    EVENT_NAME,
    EVENT_STATES,
    PHASES,
    STATE_NO_POWER,
    STATE_NORMAL,
    STATE_OPTIONS,
    STATE_OUTAGE,
    STATE_TRIP,
    conf_indicators,
    conf_input,
)

TICK = timedelta(seconds=5)
BEFORE_WINDOW = timedelta(seconds=120)

RESTORE_KEYS = (
    "protection_trip_count",
    "grid_outage_count",
    "no_power_count",
    "last_event_type",
    "last_event_start",
    "last_event_end",
    "last_event_duration_s",
    "last_voltage_before",
    "last_voltage_min_before",
    "last_voltage_max_before",
)
COUNT_KEY = {
    STATE_TRIP: "protection_trip_count",
    STATE_OUTAGE: "grid_outage_count",
    STATE_NO_POWER: "no_power_count",
}


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Phase Guard",
        model="Phase Guard",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    cfg = dict(entry.options or entry.data)
    phases: list[PhaseSensor] = []
    for n in PHASES:
        indicators = cfg.get(conf_indicators(n)) or []
        if not indicators:
            continue
        phases.append(PhaseSensor(entry, n, cfg.get(conf_input(n)) or None, indicators, cfg))
    overall = OverallSensor(entry, phases)
    for phase in phases:
        phase.listeners.append(overall.async_phase_changed)
    async_add_entities([*phases, overall])


def _is_voltage(state: State) -> bool:
    return (
        state.attributes.get("device_class") == "voltage"
        or state.attributes.get("unit_of_measurement") == "V"
    )


class PhaseSensor(SensorEntity, RestoreEntity):
    """State of one phase after its protection relay."""

    _attr_has_entity_name = True
    _attr_translation_key = "phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATE_OPTIONS
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        phase: int,
        input_entity: str | None,
        indicators: list[str],
        cfg: dict[str, Any],
    ) -> None:
        self.phase = phase
        self._input = input_entity
        self._indicators = list(indicators)
        self._input_min = float(cfg.get(CONF_INPUT_MIN_V, DEFAULT_INPUT_MIN_V))
        self._indicator_min = float(cfg.get(CONF_INDICATOR_MIN_V, DEFAULT_INDICATOR_MIN_V))
        self._max_age = float(cfg.get(CONF_INPUT_MAX_AGE, DEFAULT_INPUT_MAX_AGE))
        self._debounce = float(cfg.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE))
        self._entry_title = entry.title

        self._attr_unique_id = f"{entry.entry_id}_phase{phase}"
        self._attr_translation_placeholders = {"phase": str(phase)}
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = None

        self._history: deque[tuple[datetime, float]] = deque(maxlen=200)
        self._pending: str | None = None
        self._pending_since: datetime | None = None
        self._pending_before: tuple[float | None, float | None, float | None] = (None, None, None)
        self._event_start: datetime | None = None
        self._input_status = "none"
        self._indicator_detail: dict[str, str] = {}
        self._stats: dict[str, Any] = {k: 0 for k in COUNT_KEY.values()}
        self.listeners: list[Callable[[], None]] = []
        self._last_written: tuple | None = None

    # ---------------------------------------------------------------- lifecycle
    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            for key in RESTORE_KEYS:
                if key in last.attributes:
                    self._stats[key] = last.attributes[key]
        tracked = [e for e in [self._input, *self._indicators] if e]
        self.async_on_remove(
            async_track_state_change_event(self.hass, tracked, self._handle_state_change)
        )
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_tick, TICK))
        self._evaluate()

    @callback
    def _handle_state_change(self, event: Event) -> None:
        self._evaluate()

    @callback
    def _handle_tick(self, now: datetime) -> None:
        self._evaluate()

    # ------------------------------------------------------------------ inputs
    def _read_input(self, now: datetime) -> str:
        """Return 'none' | 'nodata' | 'present' | 'absent' for the house input."""
        if not self._input:
            return "none"
        state = self.hass.states.get(self._input)
        if state is None:
            return "nodata"
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return "nodata"
        stamp = getattr(state, "last_reported", None) or state.last_updated
        if not self._history or self._history[-1][0] != stamp:
            self._history.append((stamp, value))
        if (now - stamp).total_seconds() > self._max_age:
            return "nodata"
        return "present" if value >= self._input_min else "absent"

    def _read_indicators(self) -> bool | None:
        """True if any indicator is alive, False if all known ones are dead."""
        detail: dict[str, str] = {}
        alive: list[bool] = []
        for entity_id in self._indicators:
            state = self.hass.states.get(entity_id)
            if state is None or state.state == STATE_UNKNOWN:
                detail[entity_id] = "unknown"
                continue
            if state.state == STATE_UNAVAILABLE:
                ok = False
            elif _is_voltage(state):
                try:
                    ok = float(state.state) >= self._indicator_min
                except ValueError:
                    ok = True
            else:
                ok = True
            detail[entity_id] = "alive" if ok else "dead"
            alive.append(ok)
        self._indicator_detail = detail
        if not alive:
            return None
        return any(alive)

    def _voltage_before(self, moment: datetime) -> tuple[float | None, float | None, float | None]:
        window = [v for t, v in self._history if moment - BEFORE_WINDOW <= t <= moment]
        last = [v for t, v in self._history if t <= moment]
        return (
            last[-1] if last else None,
            min(window) if window else None,
            max(window) if window else None,
        )

    # ----------------------------------------------------------------- logic
    @callback
    def _evaluate(self) -> None:
        now = dt_util.utcnow()
        self._input_status = self._read_input(now)
        downstream = self._read_indicators()

        current = self._attr_native_value
        in_event = current in EVENT_STATES

        if in_event:
            if downstream:
                self._end_event(now)
                self._attr_native_value = STATE_NORMAL
            elif downstream is False and current == STATE_TRIP and self._input_status == "absent":
                # The relay had cut the phase, and now the input itself is really gone.
                # (A mere data gap keeps the trip; an outage stays an outage while the
                # relay waits to reconnect after the grid returns.)
                self._stats["last_event_type"] = STATE_OUTAGE
                self._attr_native_value = STATE_OUTAGE
            # downstream None (indicators unknown): keep the event running
        elif downstream is False:
            if self._pending_since is None:
                self._pending_since = now
                self._pending_before = self._voltage_before(now)
            kind = self._classify_new(now)
            self._pending = kind
            if kind and (now - self._pending_since).total_seconds() >= self._debounce:
                self._start_event(kind)
                self._attr_native_value = kind
        else:
            self._pending = None
            self._pending_since = None
            self._attr_native_value = STATE_NORMAL if downstream else None

        self._write_if_changed()

    def _classify_new(self, now: datetime) -> str | None:
        """Decide why the phase went dead; None while it is still unclear.

        A protection trip needs proof that the meter upstream of the relay is still
        alive: a reading that arrived after the downstream side died. The meter
        loses power in a real outage, so no such reading ever comes.
        """
        if not self._input:
            return STATE_NO_POWER
        since = self._pending_since
        after = [v for t, v in self._history if t > since]
        if after:
            return STATE_TRIP if after[-1] >= self._input_min else STATE_OUTAGE
        if (now - since).total_seconds() > self._max_age:
            return STATE_OUTAGE
        return None

    def _start_event(self, kind: str) -> None:
        start = self._pending_since or dt_util.utcnow()
        v_last, v_min, v_max = self._pending_before
        self._event_start = start
        self._stats[COUNT_KEY[kind]] = int(self._stats.get(COUNT_KEY[kind], 0)) + 1
        self._stats.update(
            {
                "last_event_type": kind,
                "last_event_start": start.isoformat(),
                "last_event_end": None,
                "last_event_duration_s": None,
                "last_voltage_before": v_last,
                "last_voltage_min_before": v_min,
                "last_voltage_max_before": v_max,
            }
        )
        self._pending = None
        self._pending_since = None
        self.hass.bus.async_fire(
            EVENT_NAME,
            {
                "entry": self._entry_title,
                "phase": self.phase,
                "type": kind,
                "stage": "start",
                "start": start.isoformat(),
                "voltage_before": v_last,
                "voltage_min_before": v_min,
                "voltage_max_before": v_max,
            },
        )

    def _end_event(self, now: datetime) -> None:
        start = self._event_start
        duration = round((now - start).total_seconds()) if start else None
        self._stats["last_event_end"] = now.isoformat()
        self._stats["last_event_duration_s"] = duration
        self._event_start = None
        self.hass.bus.async_fire(
            EVENT_NAME,
            {
                "entry": self._entry_title,
                "phase": self.phase,
                "type": self._stats.get("last_event_type"),
                "stage": "end",
                "start": start.isoformat() if start else None,
                "end": now.isoformat(),
                "duration_s": duration,
            },
        )

    # ---------------------------------------------------------------- output
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "input_entity": self._input,
            "input_status": self._input_status,
            "indicators": self._indicator_detail,
            **self._stats,
        }

    @callback
    def _write_if_changed(self) -> None:
        snapshot = (
            self._attr_native_value,
            self._input_status,
            tuple(sorted(self._indicator_detail.items())),
            tuple(sorted((k, str(v)) for k, v in self._stats.items())),
        )
        if snapshot == self._last_written:
            return
        self._last_written = snapshot
        self.async_write_ha_state()
        for listener in self.listeners:
            listener()


class OverallSensor(SensorEntity):
    """Worst state across all monitored phases."""

    _attr_has_entity_name = True
    _attr_translation_key = "overall"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATE_OPTIONS
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, phases: list[PhaseSensor]) -> None:
        self._phases = phases
        self._attr_unique_id = f"{entry.entry_id}_overall"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        self._recalc()

    @callback
    def async_phase_changed(self) -> None:
        if self.hass is None:
            return
        self._recalc()
        self.async_write_ha_state()

    def _recalc(self) -> None:
        states = [p.native_value for p in self._phases]
        for kind in (STATE_OUTAGE, STATE_TRIP, STATE_NO_POWER):
            if kind in states:
                self._attr_native_value = kind
                break
        else:
            self._attr_native_value = (
                STATE_NORMAL if states and all(s == STATE_NORMAL for s in states) else None
            )
        self._attr_extra_state_attributes = {
            f"phase_{p.phase}": p.native_value for p in self._phases
        }
