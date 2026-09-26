"""`domain/conversation_graph/severity.py` — severity resolution and routing."""

from __future__ import annotations

from app.domain.conversation_graph.graph import Node
from app.domain.conversation_graph.severity import (
    resolve_severity,
    route_after_severity,
    severity_to_urgency,
)
from app.domain.conversation_graph.state import Severity
from app.domain.enums import Urgency


def test_safety_trigger_always_forces_s4_regardless_of_llm_proposal() -> None:
    assert resolve_severity(llm_proposed=Severity.s1, safety_triggered=True) == Severity.s4
    assert resolve_severity(llm_proposed=None, safety_triggered=True) == Severity.s4


def test_llm_proposal_used_when_no_safety_trigger() -> None:
    assert resolve_severity(llm_proposed=Severity.s3, safety_triggered=False) == Severity.s3


def test_missing_llm_proposal_defaults_to_s2_not_s0() -> None:
    # Never silently downgrade to routine (CLAUDE.md rule 6).
    assert resolve_severity(llm_proposed=None, safety_triggered=False) == Severity.s2


def test_route_s4_goes_to_escalate_urgent() -> None:
    assert route_after_severity(Severity.s4) == Node.escalate_urgent


def test_route_s3_goes_to_escalate_standard() -> None:
    assert route_after_severity(Severity.s3) == Node.escalate_standard


def test_route_s0_to_s2_returns_to_probe_topics() -> None:
    for severity in (Severity.s0, Severity.s1, Severity.s2):
        assert route_after_severity(severity) == Node.probe_topics


def test_severity_to_urgency_mapping() -> None:
    assert severity_to_urgency(Severity.s0) == Urgency.routine
    assert severity_to_urgency(Severity.s1) == Urgency.routine
    assert severity_to_urgency(Severity.s2) == Urgency.service_failure
    assert severity_to_urgency(Severity.s3) == Urgency.safety_concern
    assert severity_to_urgency(Severity.s4) == Urgency.safety_concern
