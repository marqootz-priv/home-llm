"""
Load seed memory from data/seed_mark_profile.json into the shared memory store.
Run once after setup or when updating the seed file: python load_seed_memory.py
Optional: Ensemble startup can call load_seed_memory.run() to load if file exists.
"""
import json
import logging
from pathlib import Path

from tools.memory import remember

logger = logging.getLogger("ensemble.seed_memory")
_SEED_PATH = Path(__file__).resolve().parent / "data" / "seed_mark_profile.json"


def run() -> int:
    """
    Load seed_memories from seed_mark_profile.json with speaker='system'.
    Returns number of keys stored, or 0 if file missing/invalid.
    """
    if not _SEED_PATH.exists():
        logger.info("Seed file not found: %s", _SEED_PATH)
        return 0
    try:
        with open(_SEED_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Failed to load seed file: %s", e)
        return 0
    entries = data.get("seed_memories") or []
    if not isinstance(entries, list):
        logger.warning("seed_memories is not a list")
        return 0
    count = 0
    for item in entries:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if not key or value is None:
            continue
        out = remember(operation="store", key=str(key).strip(), value=str(value).strip(), speaker="system")
        if out.get("ok"):
            count += 1
        else:
            logger.warning("Seed store failed for key %s: %s", key, out.get("error"))
    if count:
        logger.info("[seed_memory] loaded %d entries from %s", count, _SEED_PATH.name)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = run()
    print(f"Stored {n} seed memory entries.")
