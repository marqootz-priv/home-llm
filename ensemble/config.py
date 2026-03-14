"""Load configuration from environment and agent configs."""
import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


def _required(key: str) -> str:
    val = os.environ.get(key)
    if not val or not str(val).strip():
        raise ValueError(f"Missing required env var: {key}")
    return str(val).strip().replace("\r", "").replace("\n", "")


# Required (keys are stripped and normalized so pasted values with newlines work)
ANTHROPIC_API_KEY: str = _required("ANTHROPIC_API_KEY")
ELEVENLABS_API_KEY: str = _required("ELEVENLABS_API_KEY")
MATILDA_VOICE_ID: str = _required("MATILDA_VOICE_ID")
LEON_VOICE_ID: str = _required("LEON_VOICE_ID")
HA_URL: str = _required("HA_URL").rstrip("/")
HA_TOKEN: str = _required("HA_TOKEN")

# Optional (if unset, DuckDuckGo via ddgs is used for search_web)
BRAVE_API_KEY: str = os.environ.get("BRAVE_API_KEY", "").strip()

# Optional
ENSEMBLE_PORT: int = int(os.environ.get("ENSEMBLE_PORT", "8000"))
MEMORY_DB_PATH: str = os.environ.get("MEMORY_DB_PATH", "").strip() or str(
    Path(__file__).resolve().parent / "data" / "ensemble_memory.db"
)
CLAUDE_MODEL: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Agent IDs
MATILDA_ID = "matilda"
LEON_ID = "leon"
