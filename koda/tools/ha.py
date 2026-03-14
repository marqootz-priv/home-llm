"""Home Assistant REST API tool for Koda."""
import httpx

from config import HA_TOKEN, HA_URL

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}


def control_home(action: str, entity_id: str | None = None, service: str | None = None, service_data: dict | None = None) -> dict:
    """
    Call Home Assistant REST API.
    action: "get_state" | "call_service"
    entity_id: required for get_state; optional for call_service
    service: domain/service e.g. "light/turn_on" (for call_service)
    service_data: optional dict for service call
    """
    try:
        if action == "get_state":
            if not entity_id:
                return {"ok": False, "error": "entity_id required for get_state"}
            url = f"{HA_URL}/api/states/{entity_id}"
            with httpx.Client(timeout=10.0) as client:
                r = client.get(url, headers=HEADERS)
                r.raise_for_status()
                data = r.json()
                return {"ok": True, "state": data.get("state"), "attributes": data.get("attributes", {}), "entity_id": data.get("entity_id")}
        elif action == "call_service":
            if not service:
                return {"ok": False, "error": "service required for call_service (e.g. light/turn_on)"}
            domain, _, name = service.partition("/")
            if not name:
                return {"ok": False, "error": "service must be domain/name (e.g. light/turn_on)"}
            url = f"{HA_URL}/api/services/{domain}/{name}"
            body = service_data or {}
            if entity_id:
                body["entity_id"] = entity_id
            with httpx.Client(timeout=15.0) as client:
                r = client.post(url, headers=HEADERS, json=body)
                r.raise_for_status()
                return {"ok": True, "message": "Service call completed"}
        else:
            return {"ok": False, "error": f"Unknown action: {action}. Use get_state or call_service."}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HA API error: {e.response.status_code} — {e.response.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
