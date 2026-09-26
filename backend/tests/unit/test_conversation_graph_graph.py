"""`domain/conversation_graph/graph.py` — every legal and a representative set of illegal
transitions (PRD v2 Phase 2 acceptance check)."""

from __future__ import annotations

from app.domain.conversation_graph.graph import (
    EDGES,
    TERMINAL_NODES,
    Node,
    is_legal_edge,
    next_node,
)


def test_every_node_has_an_edges_entry() -> None:
    assert set(EDGES.keys()) == set(Node)


def test_all_legal_edges_from_the_prd_are_present() -> None:
    expected: list[tuple[Node, Node]] = [
        (Node.open_and_identify, Node.purpose_consent_time),
        (Node.open_and_identify, Node.caregiver),
        (Node.open_and_identify, Node.close_wrong),
        (Node.open_and_identify, Node.callback),
        (Node.open_and_identify, Node.opt_out),
        (Node.caregiver, Node.purpose_consent_time),
        (Node.caregiver, Node.callback),
        (Node.purpose_consent_time, Node.open_experience),
        (Node.purpose_consent_time, Node.callback),
        (Node.purpose_consent_time, Node.opt_out),
        (Node.purpose_consent_time, Node.close),
        (Node.open_experience, Node.overall_rating),
        (Node.open_experience, Node.probe_topics),
        (Node.overall_rating, Node.probe_topics),
        (Node.overall_rating, Node.anything_else),
        (Node.probe_topics, Node.complaint_detail),
        (Node.probe_topics, Node.overall_rating),
        (Node.probe_topics, Node.anything_else),
        (Node.complaint_detail, Node.severity_gate),
        (Node.severity_gate, Node.escalate_standard),
        (Node.severity_gate, Node.escalate_urgent),
        (Node.severity_gate, Node.probe_topics),
        (Node.severity_gate, Node.anything_else),
        (Node.anything_else, Node.complaint_detail),
        (Node.anything_else, Node.readback_and_next_steps),
        (Node.readback_and_next_steps, Node.close),
        (Node.readback_and_next_steps, Node.complaint_detail),
        (Node.escalate_standard, Node.probe_topics),
        (Node.escalate_urgent, Node.close),
    ]
    for src, dst in expected:
        assert is_legal_edge(src, dst), f"{src} -> {dst} should be legal"


def test_illegal_edge_is_rejected() -> None:
    # Skipping identity/consent straight to a complaint is never legal.
    assert not is_legal_edge(Node.open_and_identify, Node.complaint_detail)
    assert not is_legal_edge(Node.close, Node.open_and_identify)


def test_next_node_accepts_legal_proposal() -> None:
    assert next_node(Node.open_experience, Node.probe_topics) == Node.probe_topics


def test_next_node_rejects_illegal_proposal_and_stays_put() -> None:
    assert next_node(Node.open_and_identify, Node.close) == Node.open_and_identify


def test_terminal_nodes_never_move() -> None:
    for node in TERMINAL_NODES:
        assert next_node(node, Node.open_and_identify) == node


def test_escalate_urgent_never_returns_to_feedback_collection() -> None:
    # PRD §7.4: "After an urgent script the call does not return to feedback collection."
    assert EDGES[Node.escalate_urgent] == frozenset({Node.close})
