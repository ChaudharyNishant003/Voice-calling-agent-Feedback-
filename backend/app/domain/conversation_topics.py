"""Demo conversation topic tracking + end-of-call rule (Demo MVP spec §10-11). Pure, no I/O.

The LLM proposes ending the call (`end_call: true` in its structured output) once it judges enough
feedback is collected; this module is the deterministic ceiling around that signal — matches
doc 03's principle "state machine owns... when the call ends", not the LLM alone. A stuck or
overly chatty LLM can never make a demo call run forever (`MAX_TURNS` hard cap) or end after a
single exchange (`MIN_TURNS_BEFORE_END` floor).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

MIN_TURNS_BEFORE_END = 3
MAX_TURNS = 8


class Topic(enum.StrEnum):
    doctor = "doctor"
    staff = "staff"
    waiting_time = "waiting_time"
    cleanliness = "cleanliness"
    billing = "billing"
    overall_experience = "overall_experience"


@dataclass(frozen=True)
class TopicState:
    covered: frozenset[Topic] = frozenset()


def record_topics(state: TopicState, mentioned: frozenset[Topic]) -> TopicState:
    return TopicState(covered=state.covered | mentioned)


def should_end(*, turn_count: int, llm_wants_to_end: bool) -> bool:
    if turn_count >= MAX_TURNS:
        return True
    return llm_wants_to_end and turn_count >= MIN_TURNS_BEFORE_END
