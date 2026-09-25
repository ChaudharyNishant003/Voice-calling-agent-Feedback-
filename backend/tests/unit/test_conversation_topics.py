"""Demo conversation topic tracking + end-of-call rule (spec §10-11) — pure/no I/O."""

from __future__ import annotations

from app.domain.conversation_topics import (
    MAX_TURNS,
    MIN_TURNS_BEFORE_END,
    Topic,
    TopicState,
    record_topics,
    should_end,
)


def test_record_topics_accumulates_across_turns() -> None:
    state = TopicState()
    state = record_topics(state, frozenset({Topic.waiting_time}))
    state = record_topics(state, frozenset({Topic.doctor, Topic.staff}))
    assert state.covered == frozenset({Topic.waiting_time, Topic.doctor, Topic.staff})


def test_record_topics_is_idempotent_for_repeated_mentions() -> None:
    state = TopicState(covered=frozenset({Topic.doctor}))
    state = record_topics(state, frozenset({Topic.doctor}))
    assert state.covered == frozenset({Topic.doctor})


def test_llm_wanting_to_end_before_min_turns_is_overridden() -> None:
    assert should_end(turn_count=1, llm_wants_to_end=True) is False
    assert should_end(turn_count=MIN_TURNS_BEFORE_END - 1, llm_wants_to_end=True) is False


def test_llm_wanting_to_end_at_or_after_min_turns_is_honored() -> None:
    assert should_end(turn_count=MIN_TURNS_BEFORE_END, llm_wants_to_end=True) is True


def test_llm_not_wanting_to_end_continues_below_max_turns() -> None:
    assert should_end(turn_count=MIN_TURNS_BEFORE_END, llm_wants_to_end=False) is False
    assert should_end(turn_count=MAX_TURNS - 1, llm_wants_to_end=False) is False


def test_max_turns_forces_end_regardless_of_llm_signal() -> None:
    assert should_end(turn_count=MAX_TURNS, llm_wants_to_end=False) is True
