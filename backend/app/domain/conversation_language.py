"""Demo conversation language rule (Demo MVP spec §8 — "stable, not per-turn"). Pure, no I/O.

Hindi and Hinglish are one family (`hindi_hinglish`); code-switching between them is natural
speech, not a language switch. A real switch (family ↔ family) happens only after the customer
speaks the *other* family for 3 consecutive turns — a single off-family turn changes nothing, and
the streak resets the moment they return to the locked family. An explicit request ("English mein
baat karo") switches immediately regardless of the streak.

The LLM only *reports* what family it heard this turn (`detected`) and, when the customer explicitly
asked for a language, what they asked for (`requested`) — this module makes the actual locking
decision. Matches CLAUDE.md's "the LLM may suggest; deterministic code decides."
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

SWITCH_THRESHOLD = 3


class LanguageFamily(enum.StrEnum):
    hindi_hinglish = "hindi_hinglish"
    english = "english"


@dataclass(frozen=True)
class LanguageState:
    """`locked=None` means no customer turn has happened yet (still on the Hinglish greeting)."""

    locked: LanguageFamily | None = None
    consecutive_other_count: int = 0


@dataclass(frozen=True)
class LanguageDecision:
    state: LanguageState
    switched: bool


def decide_language(
    state: LanguageState,
    detected: LanguageFamily,
    *,
    requested: LanguageFamily | None = None,
) -> LanguageDecision:
    # First customer turn ever: locks immediately (spec rule 2). Not a "switch" — there was nothing
    # to switch from.
    if state.locked is None:
        return LanguageDecision(LanguageState(locked=detected, consecutive_other_count=0), False)

    if requested is not None and requested != state.locked:
        return LanguageDecision(LanguageState(locked=requested, consecutive_other_count=0), True)

    if detected == state.locked:
        if state.consecutive_other_count == 0:
            return LanguageDecision(state, False)
        return LanguageDecision(LanguageState(state.locked, 0), False)

    # Off-family turn, no explicit request: extend the streak; only switch at the threshold.
    streak = state.consecutive_other_count + 1
    if streak >= SWITCH_THRESHOLD:
        return LanguageDecision(LanguageState(detected, 0), True)
    return LanguageDecision(LanguageState(state.locked, streak), False)
