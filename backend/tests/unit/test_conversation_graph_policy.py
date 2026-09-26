"""`domain/conversation_graph/policy.py` — deterministic pre-LLM intent detection."""

from __future__ import annotations

import pytest

from app.domain.conversation_graph.policy import PolicyIntent, detect_policy_intent


@pytest.mark.parametrize(
    "text",
    [
        "call mat karo",
        "dobara call mat kariyega",
        "mujhe nahi chahiye",
        "stop calling me",
        "band karo",
    ],
)
def test_opt_out_detected(text: str) -> None:
    assert detect_policy_intent(text) == PolicyIntent.opt_out


@pytest.mark.parametrize(
    "text", ["kisi human se baat karni hai", "I want to talk to a real person"]
)
def test_wants_human_detected(text: str) -> None:
    assert detect_policy_intent(text) == PolicyIntent.wants_human


@pytest.mark.parametrize("text", ["kya?", "hello?", "samajh nahi aaya", "phir se bol dijiye"])
def test_repeat_request_detected(text: str) -> None:
    assert detect_policy_intent(text) == PolicyIntent.repeat_request


def test_no_policy_intent_for_ordinary_answer() -> None:
    assert detect_policy_intent("Doctor achhe the, waiting zyada thi") is None


def test_opt_out_wins_when_multiple_match() -> None:
    assert detect_policy_intent("call mat karo, kya?") == PolicyIntent.opt_out
