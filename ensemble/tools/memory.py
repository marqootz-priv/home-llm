"""SQLite memory store for Ensemble — shared between both agents, with speaker tag."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import MEMORY_DB_PATH


def _ensure_db() -> None:
    Path(MEMORY_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB_PATH)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                speaker TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def remember(
    operation: str,
    key: str | None = None,
    value: str | None = None,
    query: str | None = None,
    limit: int = 50,
    speaker: str | None = None,
) -> dict:
    """
    Shared memory store. Operations: store, retrieve, list, forget.
    store: key, value, speaker (matilda|leon) required.
    retrieve: key or query (LIKE match).
    list: return recent N (limit).
    forget: delete by key.
    """
    _ensure_db()
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            if operation == "store":
                if not key or value is None:
                    return {"ok": False, "error": "store requires key and value"}
                sp = (speaker or "matilda").strip().lower()
                if sp not in ("matilda", "leon"):
                    sp = "matilda"
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO memory (key, value, speaker, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=?, speaker=?, updated_at=?",
                    (key.strip(), str(value).strip(), sp, now, str(value).strip(), sp, now),
                )
                conn.commit()
                return {"ok": True, "message": f"Stored under '{key}'"}
            elif operation == "retrieve":
                if key:
                    row = conn.execute("SELECT key, value, speaker, updated_at FROM memory WHERE key = ?", (key.strip(),)).fetchone()
                    if row:
                        return {"ok": True, "key": row["key"], "value": row["value"], "speaker": row["speaker"], "updated_at": row["updated_at"]}
                    return {"ok": True, "key": key, "value": None}
                if query and query.strip():
                    pattern = f"%{query.strip()}%"
                    rows = conn.execute(
                        "SELECT key, value, speaker, updated_at FROM memory WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT ?",
                        (pattern, pattern, min(limit, 100)),
                    ).fetchall()
                    return {"ok": True, "matches": [{"key": r["key"], "value": r["value"], "speaker": r["speaker"], "updated_at": r["updated_at"]} for r in rows]}
                return {"ok": False, "error": "retrieve requires key or query"}
            elif operation == "list":
                rows = conn.execute(
                    "SELECT key, speaker, updated_at FROM memory ORDER BY updated_at DESC LIMIT ?",
                    (min(limit, 100),),
                ).fetchall()
                return {"ok": True, "keys": [{"key": r["key"], "speaker": r["speaker"], "updated_at": r["updated_at"]} for r in rows]}
            elif operation == "forget":
                if not key:
                    return {"ok": False, "error": "forget requires key"}
                cur = conn.execute("DELETE FROM memory WHERE key = ?", (key.strip(),))
                conn.commit()
                return {"ok": True, "message": "Deleted" if cur.rowcount else "Key not found"}
            else:
                return {"ok": False, "error": f"Unknown operation: {operation}. Use store, retrieve, list, or forget."}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
