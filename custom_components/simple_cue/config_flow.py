"""Config flow for Simple Cue."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .const import CONF_MCP_PORT, DEFAULT_MCP_PORT, DOMAIN

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_MCP_PORT, default=DEFAULT_MCP_PORT): NumberSelector(
            NumberSelectorConfig(min=1024, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
    }
)


class SimpleCueConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Simple Cue."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            port = int(user_input.get(CONF_MCP_PORT, DEFAULT_MCP_PORT))
            return self.async_create_entry(
                title="Simple Cue",
                data={CONF_MCP_PORT: port},
            )

        return self.async_show_form(step_id="user", data_schema=_STEP_USER_SCHEMA)
