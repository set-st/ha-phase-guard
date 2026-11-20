"""Config and options flow for Phase Guard."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEBOUNCE,
    CONF_INDICATOR_MIN_V,
    CONF_INPUT_MAX_AGE,
    CONF_INPUT_MIN_V,
    DEFAULT_DEBOUNCE,
    DEFAULT_INDICATOR_MIN_V,
    DEFAULT_INPUT_MAX_AGE,
    DEFAULT_INPUT_MIN_V,
    DEFAULT_NAME,
    DOMAIN,
    PHASES,
    conf_indicators,
    conf_input,
)


def _number(minimum: float, maximum: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _schema(cur: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=cur.get(CONF_NAME, DEFAULT_NAME))] = (
            selector.TextSelector()
        )
    for n in PHASES:
        fields[
            vol.Optional(conf_input(n), description={"suggested_value": cur.get(conf_input(n))})
        ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
        fields[
            vol.Optional(
                conf_indicators(n),
                description={"suggested_value": cur.get(conf_indicators(n), [])},
            )
        ] = selector.EntitySelector(selector.EntitySelectorConfig(multiple=True))
    fields[
        vol.Required(CONF_INPUT_MIN_V, default=cur.get(CONF_INPUT_MIN_V, DEFAULT_INPUT_MIN_V))
    ] = _number(0, 300, "V")
    fields[
        vol.Required(
            CONF_INDICATOR_MIN_V, default=cur.get(CONF_INDICATOR_MIN_V, DEFAULT_INDICATOR_MIN_V)
        )
    ] = _number(0, 300, "V")
    fields[
        vol.Required(
            CONF_INPUT_MAX_AGE, default=cur.get(CONF_INPUT_MAX_AGE, DEFAULT_INPUT_MAX_AGE)
        )
    ] = _number(5, 600, "s")
    fields[
        vol.Required(CONF_DEBOUNCE, default=cur.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE))
    ] = _number(0, 600, "s")
    return vol.Schema(fields)


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    if not any(user_input.get(conf_indicators(n)) for n in PHASES):
        return {"base": "no_indicators"}
    return {}


class PhaseGuardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Phase Guard."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                data = dict(user_input)
                title = data.pop(CONF_NAME, DEFAULT_NAME)
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}, True), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return PhaseGuardOptionsFlow()


class PhaseGuardOptionsFlow(config_entries.OptionsFlow):
    """Change sensors and thresholds after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        cur = dict(self.config_entry.options or self.config_entry.data)
        if user_input is not None:
            cur = user_input
        return self.async_show_form(step_id="init", data_schema=_schema(cur, False), errors=errors)
