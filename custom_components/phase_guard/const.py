"""Constants for Phase Guard."""

DOMAIN = "phase_guard"
PHASES = (1, 2, 3)

CONF_INPUT_MIN_V = "input_min_voltage"
CONF_INDICATOR_MIN_V = "indicator_min_voltage"
CONF_INPUT_MAX_AGE = "input_max_age"
CONF_DEBOUNCE = "debounce"

DEFAULT_NAME = "Phase Guard"
DEFAULT_INPUT_MIN_V = 150.0
DEFAULT_INDICATOR_MIN_V = 150.0
DEFAULT_INPUT_MAX_AGE = 30.0
DEFAULT_DEBOUNCE = 10.0

STATE_NORMAL = "normal"
STATE_TRIP = "protection_trip"
STATE_OUTAGE = "grid_outage"
STATE_NO_POWER = "no_power"
STATE_OPTIONS = [STATE_NORMAL, STATE_TRIP, STATE_OUTAGE, STATE_NO_POWER]
EVENT_STATES = {STATE_TRIP, STATE_OUTAGE, STATE_NO_POWER}

EVENT_NAME = "phase_guard_event"


def conf_input(phase: int) -> str:
    """Config key of the house-input voltage sensor for a phase."""
    return f"phase{phase}_input"


def conf_indicators(phase: int) -> str:
    """Config key of the downstream indicator entities for a phase."""
    return f"phase{phase}_indicators"
