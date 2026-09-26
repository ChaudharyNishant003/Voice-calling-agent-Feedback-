"""Severity gate (PRD v2 §6/Node 7, §7.1). Code decides the severity level and the resulting
routing — the LLM's `severity_proposal` is a suggestion (same authority model as `proposed_next`),
never the final word, matching CLAUDE.md rule 6 ("safety errs toward escalation... never downgrade
... to routine"). Pure, no I/O.
"""

from __future__ import annotations

from app.domain.conversation_graph.graph import Node
from app.domain.conversation_graph.state import Severity
from app.domain.enums import Urgency

# A safety-interrupt trigger (medical_now, self_harm, abuse, sexual_misconduct, threat,
# medication_error, discrimination, privacy) is ALWAYS S4 regardless of what the LLM proposed —
# the lexicon/safety layer already decided this is urgent (safety.py's OR logic), and downgrading
# it here would violate CLAUDE.md rule 6. `resolve_severity` takes that as a precondition via the
# `safety_triggered` flag rather than re-deriving it.


def resolve_severity(*, llm_proposed: Severity | None, safety_triggered: bool) -> Severity:
    if safety_triggered:
        return Severity.s4
    # Never silently accept a lower severity than what's plausible from context alone; absent an
    # LLM proposal, default to the safe middle (S2 — a real, loggable service failure) rather than
    # S0, since `severity_proposal: null` more likely means the LLM didn't engage than "nothing to
    # report" (a missing complaint wouldn't reach this gate at all — see pfa_call_service.py).
    return llm_proposed or Severity.s2


def route_after_severity(severity: Severity) -> Node:
    if severity == Severity.s4:
        return Node.escalate_urgent
    if severity == Severity.s3:
        return Node.escalate_standard
    return Node.probe_topics  # S0-S2: log only, back to the normal loop (caller may redirect to
    # anything_else instead if the probe budget is exhausted — that's a graph.next_node() concern)


# Maps the new S0-S4 granularity down onto the existing, coarser `complaints.urgency` enum (doc 02)
# so anything already reading that column keeps working, per the confirmed decision to extend
# existing tables rather than fork a parallel one.
_SEVERITY_TO_URGENCY = {
    Severity.s0: Urgency.routine,
    Severity.s1: Urgency.routine,
    Severity.s2: Urgency.service_failure,
    Severity.s3: Urgency.safety_concern,
    Severity.s4: Urgency.safety_concern,
}


def severity_to_urgency(severity: Severity) -> Urgency:
    return _SEVERITY_TO_URGENCY[severity]
