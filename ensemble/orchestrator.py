"""
Orchestrator: routing, deliberation, turn management.
Routes Mark's input to Matilda, Leon, or both (deliberation).
"""
import json
import logging
import re
import time
from typing import Any

import anthropic
import httpx

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LEON_ID, MATILDA_ID
from conversation import ConversationState
from agent import get_leon, get_matilda
from tools.memory import remember

logger = logging.getLogger("ensemble.orchestrator")

# Module-level client for routing classification (reused across turns)
_routing_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client(timeout=60.0))

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


def _format_ha_snapshot(entities: list[dict] | None) -> str:
    """Format HA entity snapshot for agent context. Empty if no snapshot."""
    if not entities:
        return ""
    # Limit size; each line "entity_id: state"
    max_entities = 80
    lines = []
    for e in entities[:max_entities]:
        eid = e.get("entity_id") or "?"
        state = e.get("state") or "?"
        lines.append(f"  {eid}: {state}")
    head = "Current Home Assistant entities (startup snapshot):"
    if len(entities) > max_entities:
        head += f" (showing first {max_entities} of {len(entities)})"
    return head + "\n" + "\n".join(lines)


def _addressed_agent(text: str) -> str | None:
    """If Mark addressed an agent by name, return that agent id else None."""
    t = text.strip().lower()
    if re.search(r"\bmatilda\b", t):
        return MATILDA_ID
    if re.search(r"\bleon\b", t):
        return LEON_ID
    return None


def _classification_scores(user_text: str) -> dict[str, float]:
    """Lightweight Claude call, no tools, returns matilda/leon/shared scores."""
    start = time.perf_counter()
    try:
        r = _routing_client.messages.create(
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
                    scores = {
                        "matilda": float(obj.get("matilda", 0)),
                        "leon": float(obj.get("leon", 0)),
                        "shared": float(obj.get("shared", 0)),
                    }
                    elapsed = time.perf_counter() - start
                    logger.info("[timing] routing_classification %.3fs scores=%s", elapsed, scores)
                    return scores
    except Exception:
        elapsed = time.perf_counter() - start
        logger.info("[timing] routing_classification_failed %.3fs", elapsed)
    return {"matilda": 0.5, "leon": 0.5, "shared": 0.5}


def _route(user_text: str) -> tuple[str, bool, dict[str, float]]:
    """
    Returns (active: "matilda"|"leon"|"both", deliberating: bool, scores: dict).
    Direct route = one agent, not deliberating. Deliberation = both, deliberating.
    """
    addressed = _addressed_agent(user_text)
    if addressed:
        return (addressed, False, {})

    scores = _classification_scores(user_text)
    matilda = scores.get("matilda", 0)
    leon = scores.get("leon", 0)
    shared = scores.get("shared", 0)

    if shared >= 0.4:
        return ("both", True, scores)
    if abs(matilda - leon) <= 0.2:
        return ("both", True, scores)
    if matilda > leon and matilda >= 0.75:
        return (MATILDA_ID, False, scores)
    if leon > matilda and leon >= 0.75:
        return (LEON_ID, False, scores)
    if matilda >= leon:
        return (MATILDA_ID, False, scores)
    return (LEON_ID, False, scores)


def run_turn(
    state: ConversationState,
    mark_input: str,
    ha_entities_snapshot: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """
    Process one user (Mark) input. Returns list of (agent_id, text) for this turn.
    Updates state.turns and state.context.
    ha_entities_snapshot: optional list of {entity_id, state} from HA for Matilda's context.
    """
    overall_start = time.perf_counter()
    ha_context = _format_ha_snapshot(ha_entities_snapshot)
    memory_context = _get_memory_context()

    # Resuming after a question to Mark: append his reply and run resolution only.
    if state.context.awaiting_mark:
        state.context.awaiting_mark = False
        state.append("mark", mark_input)
        transcript = state.transcript_for_agents(max_turns=40)
        # Last two agent turns from the previous deliberation (Matilda then Leon).
        agents_only = [(t.speaker, t.text) for t in state.turns if t.speaker in (MATILDA_ID, LEON_ID)]
        matilda_text = agents_only[-2][1] if len(agents_only) >= 2 and agents_only[-2][0] == MATILDA_ID else ""
        leon_text = agents_only[-1][1] if agents_only and agents_only[-1][0] == LEON_ID else ""
        # Default Matilda as operator for wrap-up when resuming.
        final_agent = get_matilda()
        final_agent_id = MATILDA_ID
        resolve_prompt = (
            f"Conversation:\n{transcript}\n\n"
            f"Matilda said: {matilda_text}\nLeon said: {leon_text}\n\n"
            f"Mark just replied: {mark_input}. Give the final answer or a brief wrap-up. Do not repeat what was already said. Speak directly to Mark."
        )
        if ha_context:
            resolve_prompt = ha_context + "\n\n" + resolve_prompt
        resolve_start = time.perf_counter()
        final_text = final_agent.run(user_message=resolve_prompt, memory_context=memory_context)
        resolve_elapsed = time.perf_counter() - resolve_start
        logger.info("[timing] resolution (resume awaiting_mark) agent=matilda %.3fs", resolve_elapsed)
        state.append(final_agent_id, final_text)
        overall_elapsed = time.perf_counter() - overall_start
        logger.info("[timing] run_turn resume_awaiting_mark total=%.3fs", overall_elapsed)
        return [(final_agent_id, final_text)]

    state.append("mark", mark_input)
    transcript = state.transcript_for_agents(max_turns=40)

    route_start = time.perf_counter()
    active, deliberating, scores = _route(mark_input)
    route_elapsed = time.perf_counter() - route_start
    logger.info(
        "[timing] route mark_input=%.40r active=%s deliberating=%s scores=%s %.3fs",
        mark_input,
        active,
        deliberating,
        scores,
        route_elapsed,
    )
    state.context.active_agent = active
    state.context.deliberating = deliberating
    state.context.topic = mark_input[:100]

    turns_out: list[tuple[str, str]] = []

    if not deliberating:
        # Single agent responds
        single_start = time.perf_counter()
        if active == MATILDA_ID:
            agent = get_matilda()
        else:
            agent = get_leon()
        prompt = f"Conversation so far:\n{transcript}\n\nMark's latest (respond concisely in plain spoken English): {mark_input}"
        if active == MATILDA_ID and ha_context:
            prompt = ha_context + "\n\n" + prompt
        text = agent.run(user_message=prompt, memory_context=memory_context)
        single_elapsed = time.perf_counter() - single_start
        logger.info(
            "[timing] single_agent_turn agent=%s %.3fs", "matilda" if active == MATILDA_ID else "leon", single_elapsed
        )
        state.append(active, text)
        turns_out.append((active, text))
        state.context.awaiting_mark = False
        overall_elapsed = time.perf_counter() - overall_start
        logger.info("[timing] run_turn single_agent total=%.3fs", overall_elapsed)
        return turns_out

    # Deliberation: Matilda first, then Leon
    matilda_agent = get_matilda()
    leon_agent = get_leon()

    prompt_matilda = (
        f"Conversation so far:\n{transcript}\n\n"
        "Mark's latest (you're in a short deliberation with Leon). Give your read in 1-2 sentences, no tools yet. Plain spoken English: "
        + mark_input
    )
    if ha_context:
        prompt_matilda = ha_context + "\n\n" + prompt_matilda
    matilda_start = time.perf_counter()
    matilda_text = matilda_agent.run(user_message=prompt_matilda, memory_context=memory_context)
    matilda_elapsed = time.perf_counter() - matilda_start
    logger.info("[timing] deliberation_matilda %.3fs", matilda_elapsed)
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
    leon_start = time.perf_counter()
    leon_text = leon_agent.run(user_message=prompt_leon, memory_context=memory_context)
    leon_elapsed = time.perf_counter() - leon_start
    logger.info("[timing] deliberation_leon %.3fs", leon_elapsed)
    state.append(LEON_ID, leon_text)
    turns_out.append((LEON_ID, leon_text))

    # If Leon (or the exchange) asked Mark a clarifying question, pause for his reply.
    def _is_question_to_mark(t: str) -> bool:
        t = (t or "").strip()
        if not t.endswith("?"):
            return False
        lower = t.lower()
        return "mark" in lower or " you " in lower or " your " in lower or "you?" in lower
    if _is_question_to_mark(leon_text):
        state.context.awaiting_mark = True
        overall_elapsed = time.perf_counter() - overall_start
        logger.info("[timing] run_turn deliberation awaiting_mark (no resolution) total=%.3fs", overall_elapsed)
        return turns_out

    # Resolution: route to the higher-scoring agent. Leon owns research-heavy topics;
    # Matilda owns execution/home-control-heavy topics. Tied or shared → Matilda as operator.
    leon_score = scores.get("leon", 0)
    matilda_score = scores.get("matilda", 0)
    if leon_score > matilda_score:
        final_agent = get_leon()
        final_agent_id = LEON_ID
    else:
        final_agent = get_matilda()
        final_agent_id = MATILDA_ID

    resolve_prompt = (
        f"Conversation:\n{transcript}\n\n"
        f"Matilda said: {matilda_text}\nLeon said: {leon_text}\n\n"
        "You are giving Mark the final answer. If tools are needed (home control, search, memory), use them and then respond. "
        "If Matilda and Leon already answered his question fully above, add only a brief one-line wrap-up (or a single short closing), not a full repeat. "
        "Do not restate or paraphrase what Matilda or Leon already said. If the question is not yet fully answered, give only the missing part. "
        "Output only what you say to Mark — no reasoning. Speak directly: "
        + mark_input
    )
    if final_agent_id == MATILDA_ID and ha_context:
        resolve_prompt = ha_context + "\n\n" + resolve_prompt
    resolve_start = time.perf_counter()
    final_text = final_agent.run(user_message=resolve_prompt, memory_context=memory_context)
    resolve_elapsed = time.perf_counter() - resolve_start
    logger.info(
        "[timing] resolution agent=%s %.3fs",
        "leon" if final_agent_id == LEON_ID else "matilda",
        resolve_elapsed,
    )
    state.append(final_agent_id, final_text)
    turns_out.append((final_agent_id, final_text))

    state.context.deliberating = False
    state.context.awaiting_mark = False
    overall_elapsed = time.perf_counter() - overall_start
    logger.info("[timing] run_turn deliberation total=%.3fs", overall_elapsed)
    return turns_out
