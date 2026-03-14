"""ElevenLabs TTS: convert response text to audio bytes."""
from elevenlabs.client import ElevenLabs

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID


def text_to_speech(text: str) -> bytes:
    """Return MP3 audio bytes for the given text. Empty string returns empty bytes."""
    if not text or not text.strip():
        return b""
    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    audio = client.text_to_speech.convert(
        text=text.strip(),
        voice_id=ELEVENLABS_VOICE_ID,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_128",
    )
    if isinstance(audio, bytes):
        return audio
    return b"".join(audio)
