"""Demo conversation language rule (spec §8, §21's test script) — every case, pure/no I/O."""

from __future__ import annotations

from app.domain.conversation_language import LanguageFamily, LanguageState, decide_language

HI = LanguageFamily.hindi_hinglish
EN = LanguageFamily.english


def test_first_customer_turn_locks_immediately_not_a_switch() -> None:
    decision = decide_language(LanguageState(), HI)
    assert decision.state.locked == HI
    assert decision.state.consecutive_other_count == 0
    assert decision.switched is False


def test_single_off_family_turn_does_not_switch() -> None:
    state = LanguageState(locked=HI, consecutive_other_count=0)
    decision = decide_language(state, EN)
    assert decision.state.locked == HI
    assert decision.state.consecutive_other_count == 1
    assert decision.switched is False


def test_returning_to_locked_family_resets_the_streak() -> None:
    state = LanguageState(locked=HI, consecutive_other_count=1)
    decision = decide_language(state, HI)
    assert decision.state.locked == HI
    assert decision.state.consecutive_other_count == 0
    assert decision.switched is False


def test_hindi_and_hinglish_are_one_family_never_a_switch() -> None:
    # Both map to the same LanguageFamily.hindi_hinglish before this function ever sees them —
    # this test documents that assumption rather than re-testing detection (detection is the LLM
    # adapter's job, not this pure module's).
    state = LanguageState(locked=HI, consecutive_other_count=2)
    decision = decide_language(state, HI)
    assert decision.state.consecutive_other_count == 0
    assert decision.switched is False


def test_three_consecutive_off_family_turns_switches() -> None:
    state = LanguageState(locked=HI, consecutive_other_count=0)
    for expected_count, expected_switch in [(1, False), (2, False), (3, None)]:
        decision = decide_language(state, EN)
        if expected_switch is None:  # third turn
            assert decision.switched is True
            assert decision.state.locked == EN
            assert decision.state.consecutive_other_count == 0
        else:
            assert decision.switched is False
            assert decision.state.consecutive_other_count == expected_count
        state = decision.state


def test_explicit_request_switches_immediately_regardless_of_streak() -> None:
    state = LanguageState(locked=HI, consecutive_other_count=0)
    decision = decide_language(state, HI, requested=EN)
    assert decision.switched is True
    assert decision.state.locked == EN
    assert decision.state.consecutive_other_count == 0


def test_explicit_request_matching_current_lock_is_not_a_switch() -> None:
    state = LanguageState(locked=HI, consecutive_other_count=1)
    decision = decide_language(state, HI, requested=HI)
    assert decision.switched is False
    assert decision.state.locked == HI


def test_full_spec_21_language_script() -> None:
    # Turn 1: "जी बताइए, overall ठीक था लेकिन waiting बहुत ज्यादा थी।" -> Hindi/Hinglish locked.
    state = LanguageState()
    decision = decide_language(state, HI)
    assert decision.state.locked == HI and not decision.switched
    state = decision.state

    # One English turn -> agent stays Hindi/Hinglish.
    decision = decide_language(state, EN)
    assert decision.state.locked == HI and not decision.switched
    state = decision.state

    # Back to Hindi/Hinglish -> streak resets.
    decision = decide_language(state, HI)
    assert decision.state.consecutive_other_count == 0
    state = decision.state

    # Three consecutive English turns -> switches to English.
    decision = decide_language(state, EN)
    assert not decision.switched
    state = decision.state
    decision = decide_language(state, EN)
    assert not decision.switched
    state = decision.state
    decision = decide_language(state, EN)
    assert decision.switched and decision.state.locked == EN
    state = decision.state

    # "Hindi mein baat karo" -> immediate switch back.
    decision = decide_language(state, EN, requested=HI)
    assert decision.switched and decision.state.locked == HI
