"""Structured LLM turn contract for the demo conversation engine (Demo MVP spec §12).

Pydantic, not a domain dataclass — this is exactly the "boundary" CLAUDE.md §8 means (external,
untrusted LLM output gets validated on the way in). `LLMAdapter.complete()` already returns
`LLMResult(data: dict[str, object], ...)`, so both adapters parse the vendor's JSON into this model
and hand back `.model_dump()` as `data` — the interface itself needs no change.

Extends the spec's example shape with `requested_language`: distinguishing "the customer spoke in
X this turn" (`detected_language`, always present) from "the customer explicitly asked to switch to
X" (`requested_language`, only set on an explicit ask like "English mein baat karo") is required for
`domain/conversation_language.py`'s rule to actually implement spec §8 rule 5 — the two are
different signals and collapsing them loses the "immediate switch on explicit request" behavior.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Topic = Literal["doctor", "staff", "waiting_time", "cleanliness", "billing", "overall_experience"]
DetectedLanguage = Literal["hi", "hinglish", "en"]
NextAction = Literal["greet", "ask_feedback", "follow_up", "acknowledge", "summarize", "close"]


class DemoTurnResponse(BaseModel):
    response: str = Field(description="What the agent says next — short, natural, one question.")
    detected_language: DetectedLanguage = Field(
        description="Language family the customer's last message was in."
    )
    requested_language: Literal["hi", "en"] | None = Field(
        default=None,
        description=(
            "Set ONLY if the customer explicitly asked to switch language this turn "
            "(e.g. 'English mein baat karo', 'please speak in Hindi'). Otherwise null."
        ),
    )
    topics: list[Topic] = Field(
        default_factory=list, description="Feedback topic(s) the customer just mentioned, if any."
    )
    next_action: NextAction
    end_call: bool = Field(
        default=False, description="True once enough feedback is collected and it's time to close."
    )
    summary: str | None = Field(
        default=None, description="One-line summary of the feedback, only set when end_call=true."
    )
