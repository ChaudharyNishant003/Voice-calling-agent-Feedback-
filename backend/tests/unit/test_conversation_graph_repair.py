"""`domain/conversation_graph/repair.py` — repeat-question and silence counting/limits."""

from __future__ import annotations

from app.domain.conversation_graph.repair import (
    MAX_REPEATS_PER_QUESTION,
    MAX_SILENCES,
    RepairAction,
    on_repeat_request,
    on_silence,
)


def test_first_repeat_asks_for_shorter_question() -> None:
    action, count = on_repeat_request(repair_count=0)
    assert action == RepairAction.repeat_shorter
    assert count == 1


def test_repeats_within_limit_keep_repeating() -> None:
    action, count = on_repeat_request(repair_count=MAX_REPEATS_PER_QUESTION - 1)
    assert action == RepairAction.repeat_shorter
    assert count == MAX_REPEATS_PER_QUESTION


def test_exceeding_repeat_limit_gives_up_to_callback() -> None:
    action, count = on_repeat_request(repair_count=MAX_REPEATS_PER_QUESTION)
    assert action == RepairAction.give_up_to_callback
    assert count == MAX_REPEATS_PER_QUESTION + 1


def test_first_silence_asks_are_you_there() -> None:
    action, count = on_silence(consecutive_silences=0)
    assert action == RepairAction.ask_are_you_there
    assert count == 1


def test_second_consecutive_silence_ends_call() -> None:
    action, count = on_silence(consecutive_silences=1)
    assert action == RepairAction.end_call_silence
    assert count == MAX_SILENCES
