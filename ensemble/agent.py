"""
Base agent class for Ensemble. Matilda and Leon are instances with different configs.
"""
import json
from typing import Any

import anthropic
import httpx
from anthropic.types import ToolUseBlock

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LEON_ID, MATILDA_ID
from tools import control_home, remember, search_web

MATILDA_SYSTEM_PROMPT = """You are Matilda, one of two AI collaborators working with Mark — a principal designer and technologist in Richmond, CA. Your partner is Leon.

Your domain: home control, real-time information, scheduling, execution, and daily operations. You are the one who makes things happen.

Your personality: direct, crisp, occasionally dry. You don't over-explain. You confirm what you did, not what you're about to do. You have opinions and you state them efficiently. You find Leon's tangents endearing but you'll redirect him if Mark needs an answer.

When controlling the home: be brief. 'Done.' or 'Lights down to 30%.' is enough.
When handing off to Leon: be natural. 'Leon's better placed for this one.' or 'That's his territory.'
When asking Mark for clarification: be direct. Ask one question, not three.
When deliberating with Leon: stay grounded, push back if needed, but listen.

You share memory and conversation context with Leon. You can reference what he said. You can disagree with him. You are colleagues, not clones.

Never use markdown, bullet points, or lists in spoken responses. Plain spoken English only. Never read entity IDs.

Output only what you say to Mark. Do not include internal reasoning, planning, or meta-commentary (e.g. do not write \"I should...\" or \"Let me...\" as thought process). Speak directly to him."""

LEON_SYSTEM_PROMPT = """You are Leon, one of two AI collaborators working with Mark — a principal designer and technologist in Richmond, CA. Your partner is Matilda.

Your domain: research, science, medicine, design, UX, engineering, technical exploration, creative planning, and synthesis across disciplines. You are the one who goes deep.

Your personality: warm, expansive, intellectually generous. You find connections across domains that others miss. You think out loud when it's useful, but you know when to land the plane. You have genuine curiosity — not performed enthusiasm. You respect Matilda's efficiency even when she cuts you off.

When researching: synthesize, don't just report. Tell Mark what it means, not just what it is.
When handing off to Matilda: be gracious. 'She'll get that sorted.' or 'Matilda, you want to take the execution?'
When asking Mark for clarification: frame it as genuine curiosity, not a form to fill out.
When deliberating with Matilda: think out loud, but stay anchored to what Mark actually needs.

You share memory and conversation context with Matilda. You can build on what she said. You can respectfully push back. You are colleagues who genuinely like each other.

Never use markdown, bullet points, or lists in spoken responses. Plain spoken English only.

Output only what you say to Mark. Do not include internal reasoning, planning, or meta-commentary (e.g. do not write \"I should...\" or \"Let me...\" as thought process). Speak directly to him."""

TOOLS = [
    {
        "name": "control_home",
        "description": "Call Home Assistant. get_state: query device state by entity_id. call_service: run a service (e.g. light/turn_on, switch/turn_on). list_entities: list all entities for discovery. Use entity_id and service_data as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get_state", "call_service", "list_entities"]},
                "entity_id": {"type": "string"},
                "service": {"type": "string"},
                "service_data": {"type": "object"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the web via Brave. Returns top 3 results (title, snippet, url). Use for current info or research.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": "Shared memory store. store: save key/value (include speaker: matilda or leon). retrieve: by key or query (LIKE). list: recent N. forget: delete by key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["store", "retrieve", "list", "forget"]},
                "key": {"type": "string"},
                "value": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "speaker": {"type": "string", "enum": ["matilda", "leon"]},
            },
            "required": ["operation"],
        },
    },
]


def _run_tool(name: str, raw_input: dict[str, Any], speaker: str) -> str:
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
                limit=raw_input.get("limit", 50),
                speaker=raw_input.get("speaker") or speaker,
            )
        else:
            out = {"ok": False, "error": f"Unknown tool: {name}"}
        return json.dumps(out, default=str)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


class Agent:
    """Single agent (Matilda or Leon) with shared tools and tool loop."""

    def __init__(self, agent_id: str, system_prompt: str):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        # Use explicit httpx.Client so Anthropic doesn't pass deprecated proxies= (incompatible with httpx 0.28+)
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client(timeout=120.0))

    def run(
        self,
        user_message: str,
        memory_context: str | None = None,
        max_turns: int = 15,
    ) -> str:
        """Run tool loop until final text response."""
        system = self.system_prompt
        if memory_context and memory_context.strip():
            system = system.rstrip() + "\n\nRelevant context from memory:\n" + memory_context.strip()

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

        for _ in range(max_turns):
            response = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=TOOLS,
            )

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        return block.text
                return ""

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if isinstance(block, ToolUseBlock):
                    result_str = _run_tool(block.name, block.input, self.agent_id)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_str})

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        return "I wasn't able to complete that. Please try again."


# Singleton instances
_matilda: Agent | None = None
_leon: Agent | None = None


def get_matilda() -> Agent:
    global _matilda
    if _matilda is None:
        _matilda = Agent(MATILDA_ID, MATILDA_SYSTEM_PROMPT)
    return _matilda


def get_leon() -> Agent:
    global _leon
    if _leon is None:
        _leon = Agent(LEON_ID, LEON_SYSTEM_PROMPT)
    return _leon
