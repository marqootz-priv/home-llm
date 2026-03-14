"""
Ensemble: multi-agent voice assistant. FastAPI app with OpenAI-compatible /v1/chat/completions.
"""
import logging
import uuid

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from conversation import ConversationState
from orchestrator import run_turn
from tts import build_audio_queue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ensemble")

app = FastAPI(title="Ensemble", version="0.1.0")

# Single in-memory conversation state (single-user / single HA pipeline)
_state = ConversationState()


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


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from config import ENSEMBLE_PORT
    uvicorn.run(app, host="0.0.0.0", port=ENSEMBLE_PORT)
