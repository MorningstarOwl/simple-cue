"""Config flow for Simple Cue."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_AGENT_ID, DOMAIN


def _agent_options(hass) -> list[SelectOptionDict]:
    """Return a list of available conversation agents for the selector."""
    agents = conversation.async_get_agent_info(hass)
    return [
        SelectOptionDict(value=info.id, label=info.name)
        for info in agents
        # Exclude ourselves to avoid loops
        if not info.id.startswith(f"conversation.{DOMAIN}")
    ]


class SimpleCueConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Simple Cue."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Only allow a single instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Simple Cue",
                data={CONF_AGENT_ID: user_input[CONF_AGENT_ID]},
            )

        options = _agent_options(self.hass)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AGENT_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SimpleCueOptionsFlow(config_entry)


class SimpleCueOptionsFlow(OptionsFlow):
    """Handle options for Simple Cue (change the underlying agent)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        if user_input is not None:
            # Merge new agent_id into the config entry data
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={**self._config_entry.data, CONF_AGENT_ID: user_input[CONF_AGENT_ID]},
            )
            return self.async_create_entry(title="", data={})

        current_agent = self._config_entry.data.get(CONF_AGENT_ID, "")
        options = _agent_options(self.hass)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AGENT_ID, default=current_agent): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
