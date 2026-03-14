"""
Koda voice assistant — FastAPI app with OpenAI-compatible /v1/chat/completions.
Home Assistant's extended_openai_conversation talks to this; responses can be text or audio.
"""
import json
import uuid
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from agent import run as agent_run
from config import CLAUDE_MODEL
from tools.memory import remember
from tts import text_to_speech

app = FastAPI(title="Koda", version="0.1.0")


def _get_memory_context() -> str:
    """Retrieve recent memory keys for context injection."""
    out = remember(operation="list")
    if not out.get("ok") or not out.get("keys"):
        return ""
    lines = [f"- {k['key']} (updated {k['updated_at']})" for k in out["keys"][:20]]
    return "Recent memory keys (use remember with operation retrieve to read a value):\n" + "\n".join(lines)


def _last_user_content(messages: list[dict]) -> str:
    """Extract last user message content as a single string."""
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
):
    """
    OpenAI-compatible chat completions. Accepts messages array; uses last user message.
    If ?audio=true, returns ElevenLabs audio (MP3) instead of JSON.
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
        memory_context = _get_memory_context()
        response_text = agent_run(user_message=user_text, memory_context=memory_context)
    except Exception as e:
        response_text = f"Something went wrong on my side: {e}. Please try again in a moment."

    if audio:
        try:
            audio_bytes = text_to_speech(response_text)
        except Exception as e:
            return JSONResponse(
                {"error": "TTS failed", "detail": str(e)},
                status_code=500,
            )
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
        )

    # OpenAI-style response
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    return JSONResponse({
        "id": completion_id,
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model") or CLAUDE_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
