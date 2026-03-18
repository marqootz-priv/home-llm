"""Shared conversation state and turn history for Ensemble."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

Speaker = Literal["mark", "matilda", "leon"]
ActiveAgent = Literal["matilda", "leon", "both"]


@dataclass
class Turn:
    speaker: Speaker
    text: str
    timestamp: str
    audio_bytes: bytes | None = None

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "timestamp": self.timestamp,
            "audio_bytes": None if self.audio_bytes is None else "<bytes>",
        }


@dataclass
class ConversationContext:
    active_agent: ActiveAgent = "matilda"
    deliberating: bool = False
    awaiting_mark: bool = False
    topic: str = ""

    def to_dict(self) -> dict:
        return {
            "active_agent": self.active_agent,
            "deliberating": self.deliberating,
            "awaiting_mark": self.awaiting_mark,
            "topic": self.topic,
        }


@dataclass
class ConversationState:
    turns: list[Turn] = field(default_factory=list)
    context: ConversationContext = field(default_factory=ConversationContext)

    def append(self, speaker: Speaker, text: str, audio_bytes: bytes | None = None) -> None:
        self.turns.append(
            Turn(
                speaker=speaker,
                text=text,
                timestamp=datetime.now(timezone.utc).isoformat(),
                audio_bytes=audio_bytes,
            )
        )

    def serialize(self) -> dict:
        return {
            "turns": [t.to_dict() for t in self.turns],
            "context": self.context.to_dict(),
        }

    def transcript_for_agents(self, max_turns: int | None = None) -> str:
        """
        Transcript as a string for agent context.
        If max_turns is set, only the last max_turns turns are included (caps token growth).
        """
        turns = self.turns
        if max_turns is not None and max_turns > 0 and len(turns) > max_turns:
            turns = turns[-max_turns:]
        lines = []
        for t in turns:
            name = t.speaker.capitalize()
            lines.append(f"{name}: {t.text}")
        return "\n".join(lines) if lines else "(No messages yet.)"
