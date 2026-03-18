"""ElevenLabs TTS per agent; cache by text hash; fallback to pyttsx3."""
import asyncio
import hashlib
import logging

from config import ELEVENLABS_API_KEY, LEON_VOICE_ID, MATILDA_VOICE_ID

logger = logging.getLogger("ensemble.tts")

# Cache: text_hash -> audio bytes
_audio_cache: dict[str, bytes] = {}


def _get_voice_id(agent_id: str) -> str:
    if agent_id == "leon":
        return LEON_VOICE_ID
    return MATILDA_VOICE_ID


def _render_elevenlabs(text: str, voice_id: str) -> bytes:
    if not text or not text.strip():
        return b""
    try:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio = client.text_to_speech.convert(
            text=text.strip(),
            voice_id=voice_id,
            model_id="eleven_turbo_v2_5",
            output_format="mp3_44100_128",
        )
        if isinstance(audio, bytes):
            return audio
        return b"".join(audio)
    except Exception as e:
        logger.warning("ElevenLabs failed: %s", e, exc_info=True)
        raise


def _render_pyttsx3(text: str) -> bytes:
    """Fallback: system TTS. Returns WAV bytes (client may need to handle WAV vs MP3)."""
    try:
        import os
        import tempfile

        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 150)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            engine.save_to_file(text.strip(), path)
            engine.runAndWait()
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
    except Exception as e:
        logger.warning("pyttsx3 fallback failed: %s", e, exc_info=True)
        return b""


def render(text: str, agent_id: str, use_fallback: bool = False) -> bytes:
    """
    Render text to audio for the given agent (matilda | leon).
    Caches by hash(text + agent_id). On ElevenLabs failure, falls back to pyttsx3 if use_fallback.
    """
    if not text or not text.strip():
        return b""
    cache_key = hashlib.sha256((text.strip() + "|" + agent_id).encode()).hexdigest()
    if cache_key in _audio_cache:
        return _audio_cache[cache_key]

    voice_id = _get_voice_id(agent_id)
    try:
        audio = _render_elevenlabs(text.strip(), voice_id)
    except Exception:
        if use_fallback:
            audio = _render_pyttsx3(text)
        else:
            raise
    if audio:
        _audio_cache[cache_key] = audio
    return audio


def build_audio_queue(turns: list[tuple[str, str]], use_fallback: bool = False) -> bytes:
    """Build concatenated audio for each (agent_id, text) in turns (sequential)."""
    chunks: list[bytes] = []
    for agent_id, text in turns:
        if text and text.strip():
            try:
                chunks.append(render(text, agent_id, use_fallback=use_fallback))
            except Exception as e:
                logger.warning("TTS failed for %s: %s", agent_id, e)
                try:
                    chunks.append(_render_pyttsx3(text))
                except Exception:
                    pass
    return b"".join(chunks)


async def build_audio_queue_async(turns: list[tuple[str, str]], use_fallback: bool = False) -> bytes:
    """Build concatenated audio in parallel (one task per turn). Preserves order."""
    if not turns:
        return b""

    async def render_one(agent_id: str, text: str) -> bytes:
        if not text or not text.strip():
            return b""
        try:
            return await asyncio.to_thread(render, text, agent_id, use_fallback=use_fallback)
        except Exception as e:
            logger.warning("TTS failed for %s: %s", agent_id, e)
            if use_fallback:
                return await asyncio.to_thread(_render_pyttsx3, text)
            return b""

    chunks = await asyncio.gather(*[render_one(a, t) for a, t in turns])
    return b"".join(chunks)
