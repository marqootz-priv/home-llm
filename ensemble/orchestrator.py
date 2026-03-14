"""
Orchestrator: routing, deliberation, turn management.
Routes Mark's input to Matilda, Leon, or both (deliberation).
"""
import json
import re
from typing import Any

import anthropic
import httpx

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LEON_ID, MATILDA_ID
from conversation import ConversationState
from agent import get_leon, get_matilda
from tools.memory import remember

ROUTING_PROMPT = """You classify the user's query for a two-agent system.
- Matilda: home control, scheduling, daily tasks, weather, reminders, execution, real-time info.
- Leon: research, science, medicine, design, UX, coding, technical exploration, creative planning, synthesis.
- Shared: health/wellness, creative projects, travel planning, home automation ideas, news, ambiguous queries.

Reply with exactly one JSON object, no other text: {"matilda": <0-1>, "leon": <0-1>, "shared": <0-1>}
Scores should sum to about 1.0. Example: {"matilda": 0.8, "leon": 0.1, "shared": 0.1}"""


def _get_memory_context() -> str:
    out = remember(operation="list", limit=20)
    if not out.get("ok") or not out.get("keys"):
        return ""
    lines = [f"- {k['key']} (by {k.get('speaker', '?')}, {k['updated_at']})" for k in out["keys"]]
    return "Recent memory keys (use remember retrieve to read):\n" + "\n".join(lines)


def _addressed_agent(text: str) -> str | None:
    """If Mark addressed an agent by name, return that agent id else None."""
    t = text.strip().lower()
    if t.startswith("matilda") or " matilda " in t or t.startswith("hey matilda"):
        return MATILDA_ID
    if t.startswith("leon") or " leon " in t or t.startswith("hey leon"):
        return LEON_ID
    return None


def _classification_scores(user_text: str) -> dict[str, float]:
    """Lightweight Claude call, no tools, returns matilda/leon/shared scores."""
    # Use explicit httpx.Client so Anthropic doesn't pass deprecated proxies= (incompatible with httpx 0.28+)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client(timeout=60.0))
    try:
        r = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=80,
            system=ROUTING_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
        for block in r.content:
            if hasattr(block, "text") and block.text:
                # Parse JSON from response (may be wrapped in markdown)
                raw = block.text.strip()
                for match in re.finditer(r"\{[^{}]*\}", raw):
                    obj = json.loads(match.group())
                    return {
                        "matilda": float(obj.get("matilda", 0)),
                        "leon": float(obj.get("leon", 0)),
                        "shared": float(obj.get("shared", 0)),
                    }
    except Exception:
        pass
    return {"matilda": 0.5, "leon": 0.5, "shared": 0.5}


def _route(user_text: str) -> tuple[str, bool]:
    """
    Returns (active: "matilda"|"leon"|"both", deliberating: bool).
    Direct route = one agent, not deliberating. Deliberation = both, deliberating.
    """
    addressed = _addressed_agent(user_text)
    if addressed:
        return (addressed, False)

    scores = _classification_scores(user_text)
    matilda = scores.get("matilda", 0)
    leon = scores.get("leon", 0)
    shared = scores.get("shared", 0)

    if shared >= 0.4:
        return ("both", True)
    if abs(matilda - leon) <= 0.2:
        return ("both", True)
    if matilda > leon and matilda >= 0.75:
        return (MATILDA_ID, False)
    if leon > matilda and leon >= 0.75:
        return (LEON_ID, False)
    if matilda >= leon:
        return (MATILDA_ID, False)
    return (LEON_ID, False)


def run_turn(
    state: ConversationState,
    mark_input: str,
) -> list[tuple[str, str]]:
    """
    Process one user (Mark) input. Returns list of (agent_id, text) for this turn.
    Updates state.turns and state.context.
    """
    state.append("mark", mark_input)
    memory_context = _get_memory_context()
    transcript = state.transcript_for_agents()

    active, deliberating = _route(mark_input)
    state.context.active_agent = active
    state.context.deliberating = deliberating
    state.context.topic = mark_input[:100]

    turns_out: list[tuple[str, str]] = []

    if not deliberating:
        # Single agent responds
        if active == MATILDA_ID:
            agent = get_matilda()
        else:
            agent = get_leon()
        prompt = f"Conversation so far:\n{transcript}\n\nMark's latest (respond concisely in plain spoken English): {mark_input}"
        text = agent.run(user_message=prompt, memory_context=memory_context)
        state.append(active, text)
        turns_out.append((active, text))
        state.context.awaiting_mark = False
        return turns_out

    # Deliberation: Matilda first, then Leon
    matilda_agent = get_matilda()
    leon_agent = get_leon()

    prompt_matilda = (
        f"Conversation so far:\n{transcript}\n\n"
        "Mark's latest (you're in a short deliberation with Leon). Give your read in 1-2 sentences, no tools yet. Plain spoken English: "
        + mark_input
    )
    matilda_text = matilda_agent.run(user_message=prompt_matilda, memory_context=memory_context)
    state.append(MATILDA_ID, matilda_text)
    turns_out.append((MATILDA_ID, matilda_text))

    # If Matilda asked Mark for clarification we could set awaiting_mark; for MVP we continue
    prompt_leon = (
        f"Conversation so far:\n{transcript}\n\n"
        f"Matilda just said: {matilda_text}\n\n"
        "Add your angle in 1-2 sentences. Then either one of you should take ownership and answer Mark (use tools if needed), or ask Mark one clarifying question. Plain spoken English: "
        + mark_input
    )
    # For deliberation we want Leon to respond; then we need one "owner" to run tools and produce final answer.
    # Simplified: Leon responds; then we run a single combined "resolve" step where one agent produces the final answer.
    leon_text = leon_agent.run(user_message=prompt_leon, memory_context=memory_context)
    state.append(LEON_ID, leon_text)
    turns_out.append((LEON_ID, leon_text))

    # Resolution: ask Matilda to produce final consolidated response (she's operator) or Leon if it's research-heavy.
    # We use Matilda to consolidate and run tools if needed.
    resolve_prompt = (
        f"Conversation:\n{transcript}\n\n"
        f"Matilda said: {matilda_text}\nLeon said: {leon_text}\n\n"
        "You are giving Mark the final answer. If tools are needed (home control, search, memory), use them and then respond. "
        "If Matilda and Leon already answered his question fully above, add only a brief one-line wrap-up (or a single short closing), not a full repeat. "
        "If the question is not yet fully answered, give the missing part. Output only what you say to Mark — no reasoning. Speak directly: "
        + mark_input
    )
    final_agent = get_matilda()  # default consolidator; could switch based on content
    final_text = final_agent.run(user_message=resolve_prompt, memory_context=memory_context)
    state.append(MATILDA_ID, final_text)
    turns_out.append((MATILDA_ID, final_text))

    state.context.deliberating = False
    state.context.awaiting_mark = False
    return turns_out
