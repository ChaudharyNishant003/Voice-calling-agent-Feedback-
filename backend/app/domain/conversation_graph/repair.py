"""Repair patterns (PRD v2 §6.6) — the counting/limit logic only. Which FIXED script key to speak
for each repair situation is an orchestration concern (`pfa_call_service.py` picks the script via
`scripts.py`); this module answers "how many times has this happened, and what should happen next"
so the graph doesn't repeat a question forever or wait on a dead line indefinitely. Pure, no I/O.
"""

from __future__ import annotations

import enum

MAX_REPEATS_PER_QUESTION = 2
MAX_SILENCES = 2


class RepairAction(enum.StrEnum):
    repeat_shorter = "repeat_shorter"  # rewrite the last question, shorter
    give_up_to_callback = "give_up_to_callback"  # limit hit -> CALLBACK
    ask_are_you_there = "ask_are_you_there"  # 1st silence
    end_call_silence = "end_call_silence"  # 2nd silence -> CALLBACK, call_outcome=callback


def on_repeat_request(repair_count: int) -> tuple[RepairAction, int]:
    """Returns the action and the new repair_count. Resets to 0 whenever a real (non-repeat) answer
    is received — that reset happens in the caller, not here, since this function only ever sees
    the "another repeat happened" case.
    """
    new_count = repair_count + 1
    if new_count > MAX_REPEATS_PER_QUESTION:
        return RepairAction.give_up_to_callback, new_count
    return RepairAction.repeat_shorter, new_count


def on_silence(consecutive_silences: int) -> tuple[RepairAction, int]:
    new_count = consecutive_silences + 1
    if new_count >= MAX_SILENCES:
        return RepairAction.end_call_silence, new_count
    return RepairAction.ask_are_you_there, new_count
