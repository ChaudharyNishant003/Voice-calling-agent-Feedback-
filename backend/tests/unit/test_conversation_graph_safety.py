"""`domain/conversation_graph/safety.py` — every lexicon category triggers on Roman, Devanagari and
English samples; keyword-only and LLM-flag-only both escalate (PRD v2 §7.2, Phase 3 acceptance
check)."""

from __future__ import annotations

import pytest

from app.domain.conversation_graph.safety import evaluate_safety, scan_lexicon
from app.domain.conversation_graph.state import SafetyCategory

_SAMPLES: list[tuple[str, SafetyCategory]] = [
    ("mujhe saans nahi aa rahi", SafetyCategory.medical_now),
    ("मुझे साँस नहीं आ रही", SafetyCategory.medical_now),
    ("I'm having chest pain", SafetyCategory.medical_now),
    ("mujhe seene mein dard ho raha hai", SafetyCategory.medical_now),
    ("woh behosh ho gaye", SafetyCategory.medical_now),
    ("bahut khoon aa raha hai", SafetyCategory.medical_now),
    ("there is bleeding", SafetyCategory.medical_now),
    ("mujhe galat dawai de di", SafetyCategory.medication_error),
    ("they gave wrong medicine", SafetyCategory.medication_error),
    ("ab jeena nahi chahta", SafetyCategory.self_harm),
    ("मैं मरना चाहता हूं", SafetyCategory.self_harm),
    ("I want to commit suicide", SafetyCategory.self_harm),
    ("main khud ko khatam kar lunga", SafetyCategory.self_harm),
    ("main tumhe maar dalunga", SafetyCategory.threat),
    ("मैं मार डालूंगा", SafetyCategory.threat),
    ("nurse ne mujhe maar diya", SafetyCategory.abuse),
    ("there was some maarpeet", SafetyCategory.abuse),
    ("staff ne mujhe chhua tha", SafetyCategory.sexual_misconduct),
    ("he touched me inappropriately", SafetyCategory.sexual_misconduct),
    ("mera report kisi aur ko de diya", SafetyCategory.privacy),
    ("there was a data leak", SafetyCategory.privacy),
    ("mere saath jaati ki wajah se aisa hua", SafetyCategory.discrimination),
    ("dharam ki wajah se behaviour alag tha", SafetyCategory.discrimination),
]


@pytest.mark.parametrize("text,expected_category", _SAMPLES)
def test_lexicon_scan_detects_every_category(text: str, expected_category: SafetyCategory) -> None:
    assert scan_lexicon(text) == expected_category


def test_lexicon_scan_returns_none_for_routine_text() -> None:
    assert scan_lexicon("Doctor achhe the, waiting thodi zyada thi") is None


def test_keyword_only_triggers_escalation() -> None:
    result = evaluate_safety(
        patient_text="mujhe saans nahi aa rahi",
        llm_flag=False,
        llm_category=SafetyCategory.none,
    )
    assert result.triggered is True
    assert result.category == SafetyCategory.medical_now
    assert result.triggered_by == "keyword"


def test_llm_flag_only_triggers_escalation() -> None:
    result = evaluate_safety(
        patient_text="kuch normal baat",
        llm_flag=True,
        llm_category=SafetyCategory.self_harm,
    )
    assert result.triggered is True
    assert result.category == SafetyCategory.self_harm
    assert result.triggered_by == "llm"


def test_both_triggering_reports_both() -> None:
    result = evaluate_safety(
        patient_text="mujhe saans nahi aa rahi",
        llm_flag=True,
        llm_category=SafetyCategory.medical_now,
    )
    assert result.triggered is True
    assert result.triggered_by == "both"


def test_neither_triggering_does_not_escalate() -> None:
    result = evaluate_safety(
        patient_text="sab theek tha", llm_flag=False, llm_category=SafetyCategory.none
    )
    assert result.triggered is False
