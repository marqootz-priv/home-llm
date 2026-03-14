"""SQLite conversation memory store for Koda."""
import sqlite3
from pathlib import Path
from datetime import datetime

from config import MEMORY_DB_PATH


def _ensure_db() -> None:
    Path(MEMORY_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB_PATH)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


def remember(operation: str, key: str | None = None, value: str | None = None, query: str | None = None) -> dict:
    """
    Read or write SQLite memory.
    operation: "store" | "retrieve" | "list"
    store: key + value required
    retrieve: key or query (LIKE match) for semantic-ish lookup
    list: returns recent keys
    """
    _ensure_db()
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            if operation == "store":
                if not key or value is None:
                    return {"ok": False, "error": "store requires key and value"}
                now = datetime.utcnow().isoformat() + "Z"
                conn.execute(
                    "INSERT INTO memory (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?",
                    (key.strip(), str(value).strip(), now, str(value).strip(), now),
                )
                conn.commit()
                return {"ok": True, "message": f"Stored under '{key}'"}
            elif operation == "retrieve":
                if key:
                    row = conn.execute("SELECT key, value, updated_at FROM memory WHERE key = ?", (key.strip(),)).fetchone()
                    if row:
                        return {"ok": True, "key": row["key"], "value": row["value"], "updated_at": row["updated_at"]}
                    return {"ok": True, "key": key, "value": None}
                if query and query.strip():
                    pattern = f"%{query.strip()}%"
                    rows = conn.execute(
                        "SELECT key, value, updated_at FROM memory WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT 10",
                        (pattern, pattern),
                    ).fetchall()
                    return {"ok": True, "matches": [{"key": r["key"], "value": r["value"], "updated_at": r["updated_at"]} for r in rows]}
                return {"ok": False, "error": "retrieve requires key or query"}
            elif operation == "list":
                rows = conn.execute(
                    "SELECT key, updated_at FROM memory ORDER BY updated_at DESC LIMIT 50"
                ).fetchall()
                return {"ok": True, "keys": [{"key": r["key"], "updated_at": r["updated_at"]} for r in rows]}
            else:
                return {"ok": False, "error": f"Unknown operation: {operation}. Use store, retrieve, or list."}
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
