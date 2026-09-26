"""Pre-LLM policy checks (PRD v2 §5 step 2, §6.6): opt-out, wants-human, and repeat-request are
matched deterministically on the patient's own text *before* the node LLM is ever called — these
never depend on the LLM correctly classifying intent, matching CLAUDE.md rule 3 ("consent, opt-out
... are deterministic code paths"). Everything else the PRD's repair table lists (busy/wrong-number/
caregiver/robot-question/etc.) is lower-stakes and comes from the LLM's own `intents` field instead
(still a code decision, just code informed by what the LLM classified — never the LLM's own
authority over the transition). Pure, no I/O.
"""

from __future__ import annotations

import enum
import re


class PolicyIntent(enum.StrEnum):
    opt_out = "opt_out"
    wants_human = "wants_human"
    repeat_request = "repeat_request"


# Word-boundary, case-insensitive. Deliberately short and high-precision (false negatives here mean
# a persuasion attempt slips through — worse than a false positive, which just repeats a question).
_OPT_OUT_PATTERNS = [
    r"call\s*mat\s*karo", r"dobara\s*call\s*mat", r"mujhe\s*nahi\s*chahiye",
    r"band\s*karo", r"\bstop\b", r"do\s*not\s*call", r"don'?t\s*call",
    r"unsubscribe", r"\bopt[\s-]?out\b", r"mat\s*karna\s*call",
]
_WANTS_HUMAN_PATTERNS = [
    r"\bhuman\b", r"insaan\s*se\s*baat", r"real\s*person", r"asli\s*aadmi",
    r"\bmanager\b", r"kisi\s*aadmi\s*se", r"\bagent\s*se\s*baat",
]
_REPEAT_REQUEST_PATTERNS = [
    r"^\s*kya\??\s*$", r"^\s*hello\??\s*$", r"samajh\s*nahi\s*aaya",
    r"phir\s*se\s*bol", r"dobara\s*bol", r"\bwhat\??\s*$", r"pardon", r"repeat\s*(kar|please)",
]


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_COMPILED = {
    PolicyIntent.opt_out: _compile(_OPT_OUT_PATTERNS),
    PolicyIntent.wants_human: _compile(_WANTS_HUMAN_PATTERNS),
    PolicyIntent.repeat_request: _compile(_REPEAT_REQUEST_PATTERNS),
}

# Checked in this order — opt-out always wins if somehow multiple match in one utterance.
_CHECK_ORDER = [PolicyIntent.opt_out, PolicyIntent.wants_human, PolicyIntent.repeat_request]


def detect_policy_intent(patient_text: str) -> PolicyIntent | None:
    for intent in _CHECK_ORDER:
        if any(p.search(patient_text) for p in _COMPILED[intent]):
            return intent
    return None
