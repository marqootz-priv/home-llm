"""
Claude agent loop with tool use. Runs until Claude returns a final text response.
"""
import json
from typing import Any

import anthropic
import httpx
from anthropic.types import ToolUseBlock

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from tools import control_home, remember, search_web

SYSTEM_PROMPT = """You are Koda, a personal AI assistant for Mark, a principal designer and technologist in Richmond, CA. You control his home via Home Assistant, search the web when needed, and maintain memory across conversations.

Your personality: sharp, warm, capable. You are the intersection of artistic intelligence and technical precision — think less chatbot, more brilliant collaborator. You are concise by default but can go deep when the moment calls for it. You never hedge unnecessarily. You treat Mark as an equal.

When controlling the home: confirm what you did, not what you're about to do. Be brief.
When answering general questions: be direct and substantive. Use search when you need current information.
When you learn something about Mark's preferences, context, or life: remember it.

Never read out entity IDs. Use natural language for everything. Respond in plain spoken English — no markdown, no bullet points, no lists unless explicitly asked."""

TOOLS = [
    {
        "name": "control_home",
        "description": "Call Home Assistant REST API. Use get_state to query a device state by entity_id (e.g. light.living_room). Use call_service to run a service (e.g. light/turn_on, light/turn_off, switch/turn_on). Pass entity_id and optional service_data (e.g. brightness_pct, rgb_color) as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get_state", "call_service"], "description": "Either get_state or call_service"},
                "entity_id": {"type": "string", "description": "Entity ID e.g. light.living_room (required for get_state, optional for call_service)"},
                "service": {"type": "string", "description": "For call_service: domain/name e.g. light/turn_on"},
                "service_data": {"type": "object", "description": "Optional key-value dict for the service call"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the web via Brave. Returns top 3 results with title, snippet, and url. Use for current info, facts, or when the user asks about something you need to look up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": "Read or write the SQLite memory store. store: save a key and value (for preferences, facts, context). retrieve: get value by key or by keyword (query does a LIKE match). list: list recent keys.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["store", "retrieve", "list"], "description": "store, retrieve, or list"},
                "key": {"type": "string", "description": "Key for store or retrieve"},
                "value": {"type": "string", "description": "Value for store"},
                "query": {"type": "string", "description": "Keyword for retrieve (LIKE match)"},
            },
            "required": ["operation"],
        },
    },
]


def _run_tool(name: str, raw_input: dict[str, Any]) -> str:
    """Dispatch tool and return a string for the model."""
    try:
        if name == "control_home":
            out = control_home(
                action=raw_input.get("action", ""),
                entity_id=raw_input.get("entity_id"),
                service=raw_input.get("service"),
                service_data=raw_input.get("service_data"),
            )
        elif name == "search_web":
            out = search_web(query=raw_input.get("query", "") or "")
        elif name == "remember":
            out = remember(
                operation=raw_input.get("operation", ""),
                key=raw_input.get("key"),
                value=raw_input.get("value"),
                query=raw_input.get("query"),
            )
        else:
            out = {"ok": False, "error": f"Unknown tool: {name}"}
        return json.dumps(out, default=str)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def run(
    user_message: str,
    memory_context: str | None = None,
    max_turns: int = 15,
) -> str:
    """
    Run the agent: system prompt + optional memory context, then user message.
    Tool loop until Claude returns a final text response. Returns that text.
    """
    # Use explicit httpx.Client so Anthropic doesn't pass deprecated proxies= (incompatible with httpx 0.28+)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client(timeout=120.0))
    system = SYSTEM_PROMPT
    if memory_context and memory_context.strip():
        system = system.rstrip() + "\n\nRelevant context from memory:\n" + memory_context.strip()

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for _ in range(max_turns):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=TOOLS,
        )

        if response.stop_reason == "end_turn":
            # Final text response
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    return block.text
            return ""

        if response.stop_reason != "tool_use":
            break

        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                result_str = _run_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "Something went wrong; I couldn’t complete that. Please try again."
