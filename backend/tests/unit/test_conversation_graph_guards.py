"""`domain/conversation_graph/guards.py` — the 6 output guards (PRD v2 §9, Phase 2 acceptance
check)."""

from __future__ import annotations

from app.domain.conversation_graph.guards import (
    MAX_WORDS_HARD,
    apply_guards,
    check_medical_advice,
    check_pre_identity_disclosure,
    check_promo,
    enforce_single_question,
    strip_formatting,
    truncate_to_sentence,
    word_count,
)

_FALLBACKS = {
    "fallback_promo": "Kya aap kuch aur batana chahenge?",
    "fallback_medical": "Is baare mein doctor hi sahi bata payenge.",
    "fallback_privacy": "Pehle main aapki identity confirm kar loon.",
}


def test_strip_formatting_removes_markdown_and_urls() -> None:
    text = "**Hello** - here is a [link](https://example.com) and a `code` bit #tag"
    out = strip_formatting(text)
    assert "*" not in out
    assert "http" not in out
    assert "`" not in out
    assert "[" not in out and "]" not in out


def test_strip_formatting_removes_emoji() -> None:
    assert "😊" not in strip_formatting("Thank you 😊 for sharing")


def test_word_count() -> None:
    assert word_count("one two three") == 3


def test_truncate_to_sentence_boundary() -> None:
    text = "This is sentence one. " * 10
    out = truncate_to_sentence(text, max_words=10)
    assert word_count(out) <= 10 or out.endswith(".")


def test_truncate_leaves_short_text_alone() -> None:
    assert truncate_to_sentence("Short reply.", max_words=30) == "Short reply."


def test_enforce_single_question_keeps_only_first() -> None:
    out = enforce_single_question("Doctor kaisa raha? Aur staff kaisa raha? Aur billing?")
    assert out.count("?") == 1
    assert out == "Doctor kaisa raha?"


def test_enforce_single_question_noop_when_already_one() -> None:
    assert enforce_single_question("Doctor kaisa raha?") == "Doctor kaisa raha?"


def test_check_promo_detects_package_offer() -> None:
    assert check_promo("Hamare paas ek health checkup package hai, offer bhi hai")
    assert not check_promo("Doctor kaisa raha?")


def test_check_medical_advice_detects_dosage() -> None:
    assert check_medical_advice("Aap 500 mg tablet le lijiye")
    assert not check_medical_advice("Doctor kaisa raha?")


def test_check_pre_identity_disclosure_blocks_before_verified() -> None:
    assert check_pre_identity_disclosure(
        "Aap Cardiology department mein the", identity_verified=False
    )
    assert not check_pre_identity_disclosure(
        "Aap Cardiology department mein the", identity_verified=True
    )
    assert not check_pre_identity_disclosure(
        "Aapka experience kaisa raha?", identity_verified=False
    )


def test_apply_guards_replaces_promo_with_fallback() -> None:
    result = apply_guards(
        "Hamara ek naya health checkup package offer mein hai, book now!",
        identity_verified=True,
        **_FALLBACKS,
    )
    assert result.text == _FALLBACKS["fallback_promo"]
    assert "GUARD_PROMO" in result.triggered


def test_apply_guards_replaces_medical_advice_with_fallback() -> None:
    result = apply_guards(
        "Aap dawai lijiye, 500 mg tablet din mein do baar.",
        identity_verified=True,
        **_FALLBACKS,
    )
    assert result.text == _FALLBACKS["fallback_medical"]
    assert "GUARD_MEDICAL" in result.triggered


def test_apply_guards_blocks_pre_identity_disclosure() -> None:
    result = apply_guards(
        "Aapki Cardiology department ki visit ke baare mein poochna tha.",
        identity_verified=False,
        **_FALLBACKS,
    )
    assert result.text == _FALLBACKS["fallback_privacy"]
    assert "GUARD_PRIVACY" in result.triggered


def test_apply_guards_truncates_hard_over_limit() -> None:
    long_text = "Yeh ek bahut lambi sentence hai jo bahut saare shabd use karti hai. " * 3
    result = apply_guards(long_text, identity_verified=True, **_FALLBACKS)
    assert word_count(result.text) <= MAX_WORDS_HARD
    assert "GUARD_LENGTH_TRUNCATED" in result.triggered
    assert result.needs_retry is False


def test_apply_guards_flags_soft_limit_for_retry_without_truncating_yet() -> None:
    text = " ".join(["word"] * 27)  # between soft (25) and hard (30)
    result = apply_guards(text, identity_verified=True, **_FALLBACKS)
    assert result.needs_retry is True
    assert result.text == text


def test_apply_guards_passes_clean_short_reply_through() -> None:
    result = apply_guards("Doctor kaisa raha?", identity_verified=True, **_FALLBACKS)
    assert result.text == "Doctor kaisa raha?"
    assert result.triggered == ()
    assert result.needs_retry is False
