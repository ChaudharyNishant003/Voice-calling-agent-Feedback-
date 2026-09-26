"""Code-owned call state (PRD v2 §6, §8) — pure, no I/O. This is what `pfa_call_state.state_json`
persists and what `next_node()`/policy/safety/guards all read and update. The LLM never sees or
writes this directly; `pfa_call_service.py` translates between the node contract's JSON and this.

Reuses `domain/conversation_language.py`'s `LanguageState`/`LanguageFamily`/`decide_language` for
language locking as-is (PRD §3: "keep the existing implemented rule, plus an explicit request
switches immediately" — already exactly what that module does) rather than reimplementing it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from app.domain.conversation_graph.graph import Node
from app.domain.conversation_language import LanguageState
from app.domain.enums import ConsentState, RespondentType, Sentiment


# 13 categories (PRD §6.5), replacing the old 6-topic demo enum. Old->new mapping lives in
# `pfa_call_service.py` (the I/O layer), not here, since nothing here needs to know about the old
# engine at all.
class TopicCategory(enum.StrEnum):
    doctor = "doctor"
    nursing = "nursing"
    wait_time = "wait_time"
    reception = "reception"
    cleanliness = "cleanliness"
    billing = "billing"
    pharmacy = "pharmacy"
    diagnostics = "diagnostics"
    communication = "communication"
    staff_behaviour = "staff_behaviour"
    facilities = "facilities"
    discharge = "discharge"
    appointment = "appointment"
    other = "other"


class VisitKind(enum.StrEnum):
    opd = "OPD"
    ipd = "IPD"
    diagnostics = "DIAGNOSTICS"
    emergency = "EMERGENCY"


class Register(enum.StrEnum):
    formal = "formal"
    casual = "casual"


class Severity(enum.StrEnum):
    s0 = "S0"
    s1 = "S1"
    s2 = "S2"
    s3 = "S3"
    s4 = "S4"


class SafetyCategory(enum.StrEnum):
    medical_now = "medical_now"
    self_harm = "self_harm"
    abuse = "abuse"
    sexual_misconduct = "sexual_misconduct"
    privacy = "privacy"
    discrimination = "discrimination"
    threat = "threat"
    medication_error = "medication_error"
    none = "none"


class CallOutcome(enum.StrEnum):
    completed = "completed"
    callback = "callback"
    opt_out = "opt_out"
    wrong_number = "wrong_number"
    no_consent = "no_consent"
    abandoned = "abandoned"
    escalated = "escalated"


@dataclass(frozen=True)
class TopicMention:
    category: TopicCategory
    sentiment: Sentiment
    verbatim: str
    staff_name: str | None = None


@dataclass(frozen=True)
class ComplaintDraft:
    category: TopicCategory
    description: str
    severity: Severity | None = None
    when_text: str | None = None
    where_text: str | None = None
    wants_contact: bool | None = None
    preferred_time: str | None = None
    verbatim: str = ""
    staff_name: str | None = None
    question_count: int = 0  # per-complaint, max 4 (PRD Node 6)


@dataclass(frozen=True)
class Escalation:
    complaint_index: int | None
    severity: Severity
    category: SafetyCategory | str
    triggered_by: str  # "keyword" | "llm" | "both"


@dataclass(frozen=True)
class CallState:
    node: Node = Node.open_and_identify
    visit_kind: VisitKind = VisitKind.opd
    identity_verified: bool = False
    respondent_type: RespondentType = RespondentType.unknown
    consent: ConsentState = ConsentState.not_asked

    language: LanguageState = field(default_factory=LanguageState)
    register: Register = Register.casual

    topics: tuple[TopicMention, ...] = ()
    topics_covered: frozenset[TopicCategory] = frozenset()
    priority_topics_probed: int = 0

    complaints: tuple[ComplaintDraft, ...] = ()
    current_complaint_index: int | None = None

    rating: int | None = None
    rating_inferred: bool = False
    rating_asked: bool = False

    escalations: tuple[Escalation, ...] = ()
    clinical_questions: tuple[str, ...] = ()

    readback_count: int = 0
    repair_count: int = 0  # "kya?"/repeat-question count on the current question
    consecutive_silences: int = 0

    agent_turns: int = 0
    wants_human: bool = False
    language_need: str | None = None
    do_not_call: bool = False

    call_outcome: CallOutcome | None = None
    ended: bool = False


# Hard ceiling (PRD §3): 20 agent turns or 8 minutes wall-clock -> READBACK_AND_NEXT_STEPS (or
# CLOSE if nothing to read back). Wall-clock is checked by the caller (pure code has no clock);
# `over_turn_ceiling` only checks the turn count, which is enough for `pfa_call_service.py` to also
# check elapsed time itself and treat either as the same ceiling.
MAX_AGENT_TURNS = 20


def over_turn_ceiling(state: CallState) -> bool:
    return state.agent_turns >= MAX_AGENT_TURNS
