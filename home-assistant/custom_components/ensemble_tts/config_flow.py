"""Config flow for Ensemble TTS."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv

from .const import CONF_BASE_URL, DOMAIN


class EnsembleTTSConfigFlow(config_entries.ConfigFlow, domain="ensemble_tts"):
    """Handle a config flow for Ensemble TTS."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            base_url = (user_input.get(CONF_BASE_URL) or "").strip().rstrip("/")
            if base_url:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Ensemble TTS", data={CONF_BASE_URL: base_url})
            errors["base"] = "invalid_url"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_BASE_URL): cv.string,
            }),
            errors=errors,
        )
