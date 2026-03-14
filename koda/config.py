"""Load configuration from environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (directory containing config.py's parent)
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


def _required(key: str) -> str:
    val = os.environ.get(key)
    if not val or not val.strip():
        raise ValueError(f"Missing required env var: {key}")
    return val.strip()


# Required
ANTHROPIC_API_KEY: str = _required("ANTHROPIC_API_KEY")
ELEVENLABS_API_KEY: str = _required("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID: str = _required("ELEVENLABS_VOICE_ID")
HA_URL: str = _required("HA_URL").rstrip("/")
HA_TOKEN: str = _required("HA_TOKEN")

# Optional (if unset, DuckDuckGo via ddgs is used for search_web)
BRAVE_API_KEY: str = os.environ.get("BRAVE_API_KEY", "").strip()

# Optional
_MEMORY_DEFAULT = Path(__file__).resolve().parent / "data" / "koda_memory.db"
MEMORY_DB_PATH: str = os.environ.get("MEMORY_DB_PATH", "").strip() or str(_MEMORY_DEFAULT)
CLAUDE_MODEL: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
