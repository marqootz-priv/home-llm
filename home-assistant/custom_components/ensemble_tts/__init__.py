"""
Ensemble TTS: Home Assistant TTS platform that calls the Ensemble server for audio.

Setup via UI: Settings → Devices & services → Add integration → "Ensemble TTS" → enter base_url.
The TTS entity will appear in the voice assistant pipeline dropdown once added.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Forward config entry setup to the tts platform (required for pipeline dropdown)."""
    await hass.config_entries.async_forward_entry_setups(entry, ["tts"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the tts platform for this config entry."""
    return await hass.config_entries.async_unload_platforms(entry, ["tts"])
