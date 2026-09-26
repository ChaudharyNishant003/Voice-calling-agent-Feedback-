"""Output guards (PRD v2 §9), run on every agent reply — LLM-generated or FIXED (FIXED lines pass
by construction; tests prove it). Pure, no I/O beyond loading the two static blocklists (same
rationale as `safety.py`/`scripts.py`).

The length guard's *retry* step (ask the LLM once for a shorter reply) is an orchestration concern
— `apply_guards` only does the truncate-as-last-resort fallback; `pfa_call_service.py` decides
whether to retry first, exactly mirroring `_call_llm_with_retry`'s existing shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

MAX_WORDS_SOFT = 25
MAX_WORDS_HARD = 30

_ASSETS_DIR = Path(__file__).parent / "assets"

# Department/doctor/diagnosis/visit-type/test mentions before identity is confirmed (PRD §9.6,
# CLAUDE.md "never mention department/doctor/diagnosis before identity is confirmed"). Broad by
# design — a false positive here just means a harmless line gets replaced by a FIXED one; a false
# negative would leak clinical detail to an unverified caller.
_PRE_IDENTITY_PATTERNS = [
    r"\bdepartment\b", r"\bdoctor\b", r"\bdiagnos", r"\bdischarge\b",
    r"\btest\b", r"\breport\b", r"\bappointment\b", r"\bOPD\b", r"\bIPD\b",
]

_MARKDOWN_PATTERN = re.compile(
    r"[*_`#]|^\s*[-•]\s*|\[[^\]]*\]\(([^)]*)\)|https?://\S+", re.MULTILINE
)
_EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+", re.UNICODE
)
_BRACKET_PATTERN = re.compile(r"[\[\]{}()]")


@lru_cache(maxsize=1)
def _promo_patterns() -> list[re.Pattern[str]]:
    raw = yaml.safe_load((_ASSETS_DIR / "promo_blocklist.yaml").read_text(encoding="utf-8"))
    return [re.compile(p, re.IGNORECASE) for p in raw["patterns"]]


@lru_cache(maxsize=1)
def _medical_patterns() -> list[re.Pattern[str]]:
    raw = yaml.safe_load((_ASSETS_DIR / "medical_advice_patterns.yaml").read_text(encoding="utf-8"))
    return [re.compile(p, re.IGNORECASE) for p in raw["patterns"]]


_PRE_IDENTITY_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PRE_IDENTITY_PATTERNS]


def strip_formatting(text: str) -> str:
    text = _MARKDOWN_PATTERN.sub("", text)
    text = _EMOJI_PATTERN.sub("", text)
    text = _BRACKET_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def word_count(text: str) -> int:
    return len(text.split())


def truncate_to_sentence(text: str, max_words: int = MAX_WORDS_HARD) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    last_boundary = max(truncated.rfind("."), truncated.rfind("?"), truncated.rfind("!"))
    return truncated[: last_boundary + 1] if last_boundary > 0 else truncated + "."


def enforce_single_question(text: str) -> str:
    """More than one '?' -> keep everything up to and including the first one (PRD §9.3)."""
    idx = text.find("?")
    return text if idx == -1 or text.count("?") <= 1 else text[: idx + 1]


def check_promo(text: str) -> bool:
    return any(p.search(text) for p in _promo_patterns())


def check_medical_advice(text: str) -> bool:
    return any(p.search(text) for p in _medical_patterns())


def check_pre_identity_disclosure(text: str, *, identity_verified: bool) -> bool:
    if identity_verified:
        return False
    return any(p.search(text) for p in _PRE_IDENTITY_COMPILED)


@dataclass(frozen=True)
class GuardResult:
    text: str
    triggered: tuple[str, ...]  # e.g. ("GUARD_PROMO",) — logged verbatim by the caller
    needs_retry: bool  # True only for the length guard's soft-limit case (caller may retry once)


def apply_guards(
    text: str,
    *,
    identity_verified: bool,
    fallback_promo: str,
    fallback_medical: str,
    fallback_privacy: str,
    enforce_length: bool = True,
) -> GuardResult:
    """`enforce_length=False` is for the small set of FIXED safety-escalation lines (PRD §7.4) that
    are verbatim longer than the generic 25/30-word turn budget by design — an emergency phone
    number or the Tele-MANAS helpline number must never be truncated away (CLAUDE.md rule 6: safety
    errs toward escalation, never a downgrade). Every other guard still applies regardless.
    """
    triggered: list[str] = []
    out = strip_formatting(text)
    out = enforce_single_question(out)

    if check_promo(out):
        triggered.append("GUARD_PROMO")
        return GuardResult(text=fallback_promo, triggered=tuple(triggered), needs_retry=False)

    if check_medical_advice(out):
        triggered.append("GUARD_MEDICAL")
        return GuardResult(text=fallback_medical, triggered=tuple(triggered), needs_retry=False)

    if check_pre_identity_disclosure(out, identity_verified=identity_verified):
        triggered.append("GUARD_PRIVACY")
        return GuardResult(text=fallback_privacy, triggered=tuple(triggered), needs_retry=False)

    if not enforce_length:
        return GuardResult(text=out, triggered=tuple(triggered), needs_retry=False)

    n_words = word_count(out)
    if n_words > MAX_WORDS_HARD:
        triggered.append("GUARD_LENGTH_TRUNCATED")
        out = truncate_to_sentence(out, MAX_WORDS_HARD)
        return GuardResult(text=out, triggered=tuple(triggered), needs_retry=False)
    if n_words > MAX_WORDS_SOFT:
        return GuardResult(text=out, triggered=("GUARD_LENGTH_SOFT",), needs_retry=True)

    return GuardResult(text=out, triggered=tuple(triggered), needs_retry=False)
