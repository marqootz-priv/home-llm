"""
Ensemble: multi-agent voice assistant. FastAPI app with OpenAI-compatible /v1/chat/completions.
"""
import json
import logging
import uuid
from collections import OrderedDict

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from conversation import ConversationState
from orchestrator import run_turn
from tts import build_audio_queue, build_audio_queue_async, render
from tools.ha import control_home
from load_seed_memory import run as load_seed_memory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ensemble")

app = FastAPI(title="Ensemble", version="0.1.0")

# Single in-memory conversation state (single-user / single HA pipeline)
_state = ConversationState()

# Snapshot of Home Assistant entities, populated on startup if HA_URL/HA_TOKEN valid.
_ha_entities_snapshot: list[dict] | None = None

# TTS cache: combined_text → turn_list, for the /v1/audio/speech endpoint.
# Bounded to last 5 responses so HA can call TTS slightly after the LLM call.
_tts_cache: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
_TTS_CACHE_MAX = 5

# WebSocket state subscribers (e.g. for AtomS3R / USB serial bridge to Leon's face).
_ws_state_subscribers: set[WebSocket] = set()


def _state_payload() -> dict:
    """Current conversation context for WebSocket state broadcast."""
    ctx = _state.context
    return {
        "active_agent": ctx.active_agent,
        "deliberating": ctx.deliberating,
        "awaiting_mark": ctx.awaiting_mark,
        "topic": ctx.topic or "",
    }


async def _broadcast_state() -> None:
    """Send current state to all /ws/state subscribers. Non-fatal on send errors."""
    if not _ws_state_subscribers:
        return
    payload = json.dumps(_state_payload())
    dead: set[WebSocket] = set()
    for ws in _ws_state_subscribers:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _ws_state_subscribers.discard(ws)


def _last_user_content(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                return " ".join(parts).strip() if parts else ""
    return ""


@app.on_event("startup")
async def _startup() -> None:
    """Load HA entity snapshot and seed memory (if present)."""
    global _ha_entities_snapshot
    try:
        out = control_home(action="list_entities")
        if out.get("ok") and isinstance(out.get("entities"), list):
            _ha_entities_snapshot = out["entities"]
            logger.info("[ha] loaded entities snapshot (%d entities)", len(_ha_entities_snapshot))
        else:
            logger.info("[ha] could not load entities snapshot: %s", out.get("error"))
    except Exception as e:
        logger.info("[ha] error loading entities snapshot: %s", e)
    load_seed_memory()


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    audio: bool = Query(False, alias="audio"),
    turns: bool = Query(False, alias="turns"),
):
    """
    OpenAI-compatible chat completions. Last user message = Mark's input.
    ?audio=true → return concatenated agent audio (MP3).
    ?turns=true → return full turn breakdown (which agent said what).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    messages = body.get("messages") or []
    user_text = _last_user_content(messages)
    if not user_text:
        return JSONResponse({"error": "No user message found"}, status_code=400)

    orchestrator_start = logging.getLogger("ensemble").handlers and None  # dummy to satisfy type checkers
    import time as _time

    start = _time.perf_counter()
    try:
        turn_list = run_turn(_state, user_text, ha_entities_snapshot=_ha_entities_snapshot)
    except Exception as e:
        logger.exception("Orchestrator failed")
        turn_list = [("matilda", f"Something went wrong: {e}. Please try again.")]
    finally:
        elapsed = _time.perf_counter() - start
        logger.info("[timing] chat_completions run_turn total=%.3fs", elapsed)

    # Combined text for OpenAI content
    combined_text = " ".join(t for _, t in turn_list if t).strip() or "I didn't catch that."

    # Cache turn list so /v1/audio/speech can render per-agent voices for this response
    _tts_cache[combined_text] = turn_list
    if len(_tts_cache) > _TTS_CACHE_MAX:
        _tts_cache.popitem(last=False)

    if audio:
        import time as _time_audio

        tts_start = _time_audio.perf_counter()
        try:
            audio_bytes = await build_audio_queue_async(turn_list, use_fallback=True)
        except Exception as e:
            logger.exception("TTS failed")
            return JSONResponse({"error": "TTS failed", "detail": str(e)}, status_code=500)
        tts_elapsed = _time_audio.perf_counter() - tts_start
        logger.info("[timing] chat_completions TTS total=%.3fs", tts_elapsed)
        await _broadcast_state()
        return Response(content=audio_bytes, media_type="audio/mpeg")

    # JSON response
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    content = combined_text
    if turns:
        content = combined_text  # Keep main content; include turns in a custom field if desired
    payload = {
        "id": completion_id,
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", "ensemble"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    if turns:
        payload["turns"] = [{"agent": agent, "text": text} for agent, text in turn_list]
    if _state.context.awaiting_mark:
        payload["awaiting_mark"] = True
    await _broadcast_state()
    return JSONResponse(payload)


@app.post("/v1/audio/speech")
async def audio_speech(request: Request):
    """
    OpenAI-compatible TTS endpoint. HA pipeline calls this after the LLM step.
    Looks up the turn list cached from the most recent /v1/chat/completions call and
    renders per-agent ElevenLabs voices. Falls back to Matilda's voice if text not cached.

    Configure in Home Assistant: add an openai TTS provider pointing at this server,
    then set your HA voice pipeline to use that provider instead of the built-in one.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    input_text = (body.get("input") or "").strip()
    if not input_text:
        return JSONResponse({"error": "input is required"}, status_code=400)

    turn_list = _tts_cache.get(input_text)
    import time as _time_audio

    tts_start = _time_audio.perf_counter()
    try:
        if turn_list:
            audio_bytes = await build_audio_queue_async(turn_list, use_fallback=True)
        else:
            # Text not in cache (e.g. HA sending something other than the last LLM response)
            audio_bytes = render(input_text, "matilda", use_fallback=True)
    except Exception as e:
        logger.exception("TTS failed in /v1/audio/speech")
        return JSONResponse({"error": "TTS failed", "detail": str(e)}, status_code=500)
    tts_elapsed = _time_audio.perf_counter() - tts_start
    logger.info("[timing] audio_speech TTS total=%.3fs cache_hit=%s", tts_elapsed, bool(turn_list))

    return Response(content=audio_bytes, media_type="audio/mpeg")


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    """
    WebSocket for conversation state (active_agent, deliberating, awaiting_mark, topic).
    Broadcasts after each /v1/chat/completions turn. For future use: e.g. USB serial
    bridge to AtomS3R (Leon's face) so the device can show who is speaking.
    """
    await websocket.accept()
    _ws_state_subscribers.add(websocket)
    try:
        await websocket.send_text(json.dumps(_state_payload()))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_state_subscribers.discard(websocket)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from config import ENSEMBLE_PORT
    uvicorn.run(app, host="0.0.0.0", port=ENSEMBLE_PORT)
