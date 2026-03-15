"""
Ensemble TTS platform: calls the Ensemble server /v1/audio/speech for audio.
Registered via config entry; entity appears in the voice assistant pipeline dropdown.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.tts import TextToSpeechEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ensemble TTS entity from a config entry."""
    base_url = (config_entry.data.get(CONF_BASE_URL) or "").strip().rstrip("/")
    if not base_url:
        _LOGGER.error("ensemble_tts: base_url missing from config entry")
        return
    async_add_entities([EnsembleTTSEntity(config_entry, base_url)])


class EnsembleTTSEntity(TextToSpeechEntity):
    """TTS entity for Ensemble — appears in the voice assistant pipeline dropdown."""

    _attr_supported_languages = ["en"]
    _attr_default_language = "en"
    _attr_name = "Ensemble TTS"
    _attr_has_entity_name = True

    def __init__(self, config_entry: ConfigEntry, base_url: str) -> None:
        self._base_url = base_url
        # Stable unique_id tied to the config entry so entity_id = tts.ensemble_tts
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}"

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> tuple[str | None, bytes | None]:
        """POST text to Ensemble /v1/audio/speech and return (extension, bytes)."""
        import aiohttp

        url = f"{self._base_url}/v1/audio/speech"
        payload = {"input": message, "model": "tts-1", "voice": "alloy"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        _LOGGER.warning(
                            "Ensemble TTS request failed %s: %s", resp.status, body
                        )
                        return None, None
                    data = await resp.read()
        except Exception:
            _LOGGER.exception("Ensemble TTS request error")
            return None, None

        return ("mp3", data) if data else (None, None)
