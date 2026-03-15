"""
Ensemble: multi-agent voice assistant. FastAPI app with OpenAI-compatible /v1/chat/completions.
"""
import logging
import uuid
from collections import OrderedDict

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from conversation import ConversationState
from orchestrator import run_turn
from tts import build_audio_queue, render

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ensemble")

app = FastAPI(title="Ensemble", version="0.1.0")

# Single in-memory conversation state (single-user / single HA pipeline)
_state = ConversationState()

# TTS cache: combined_text → turn_list, for the /v1/audio/speech endpoint.
# Bounded to last 5 responses so HA can call TTS slightly after the LLM call.
_tts_cache: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
_TTS_CACHE_MAX = 5


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

    try:
        turn_list = run_turn(_state, user_text)
    except Exception as e:
        logger.exception("Orchestrator failed")
        turn_list = [("matilda", f"Something went wrong: {e}. Please try again.")]

    # Combined text for OpenAI content
    combined_text = " ".join(t for _, t in turn_list if t).strip() or "I didn't catch that."

    # Cache turn list so /v1/audio/speech can render per-agent voices for this response
    _tts_cache[combined_text] = turn_list
    if len(_tts_cache) > _TTS_CACHE_MAX:
        _tts_cache.popitem(last=False)

    if audio:
        try:
            audio_bytes = build_audio_queue(turn_list, use_fallback=True)
        except Exception as e:
            logger.exception("TTS failed")
            return JSONResponse({"error": "TTS failed", "detail": str(e)}, status_code=500)
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
    try:
        if turn_list:
            audio_bytes = build_audio_queue(turn_list, use_fallback=True)
        else:
            # Text not in cache (e.g. HA sending something other than the last LLM response)
            audio_bytes = render(input_text, "matilda", use_fallback=True)
    except Exception as e:
        logger.exception("TTS failed in /v1/audio/speech")
        return JSONResponse({"error": "TTS failed", "detail": str(e)}, status_code=500)

    return Response(content=audio_bytes, media_type="audio/mpeg")


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from config import ENSEMBLE_PORT
    uvicorn.run(app, host="0.0.0.0", port=ENSEMBLE_PORT)
