"""LLM node contract (PRD v2 §8). A Pydantic boundary model — lives in `services/`, not
`domain/conversation_graph/`, per CLAUDE.md §8 ("Pydantic models at boundaries, dataclasses/attrs
in domain"); the PRD's own suggested layout lists this under `domain/` but also says to adapt to
existing repo conventions, which this does. Keeps `domain/conversation_graph/` genuinely pure.

`proposed_next` is deliberately typed as a plain non-enum string here: this Pydantic model doesn't
import `domain.conversation_graph.graph.Node` (services -> domain is fine directionally, but
keeping this model's only job "validate what the LLM sent" means it shouldn't fail validation just
because the LLM hallucinated a node name — `pfa_call_service.py` parses it into a real `Node` and
treats an unparseable one as `ILLEGAL_TRANSITION_PROPOSED`, same as any other illegal edge).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TopicCategoryLiteral = Literal[
    "doctor", "nursing", "wait_time", "reception", "cleanliness", "billing", "pharmacy",
    "diagnostics", "communication", "staff_behaviour", "facilities", "discharge", "appointment",
    "other",
]
SentimentLiteral = Literal["positive", "neutral", "negative"]
SeverityLiteral = Literal["S0", "S1", "S2", "S3", "S4"]
SafetyCategoryLiteral = Literal[
    "medical_now", "self_harm", "abuse", "sexual_misconduct", "privacy", "discrimination",
    "threat", "medication_error", "none",
]
IntentLiteral = Literal[
    "affirm", "deny", "busy", "opt_out", "wrong_person", "caregiver", "accompanied",
    "not_accompanied", "wants_human", "asks_if_ai", "asks_medical", "asks_billing_amount",
    "repeat_request", "correction", "refuses_recording", "other_language", "off_topic", "none",
]


class TopicMentionIn(BaseModel):
    category: TopicCategoryLiteral
    sentiment: SentimentLiteral
    verbatim: str = Field(max_length=200)
    staff_name: str | None = None


class ComplaintUpdateIn(BaseModel):
    category: TopicCategoryLiteral
    description: str = Field(max_length=300)
    when: str | None = None
    where: str | None = None
    wants_contact: bool | None = None
    preferred_time: str | None = None


class RatingIn(BaseModel):
    value: int | None = Field(default=None, ge=1, le=5)
    inferred: bool = False


class SafetyIn(BaseModel):
    flag: bool = False
    category: SafetyCategoryLiteral = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NodeContract(BaseModel):
    reply_text: str = Field(description="What the agent should say (ignored if the node is FIXED).")
    language_detected: Literal["hindi", "hinglish", "english", "other"]
    register: Literal["formal", "casual"] = "casual"
    intents: list[IntentLiteral] = Field(default_factory=list)
    topics: list[TopicMentionIn] = Field(default_factory=list)
    complaint_update: ComplaintUpdateIn | None = None
    rating: RatingIn | None = None
    severity_proposal: SeverityLiteral | None = None
    safety: SafetyIn = Field(default_factory=SafetyIn)
    proposed_next: str
    clinical_question: str | None = None
