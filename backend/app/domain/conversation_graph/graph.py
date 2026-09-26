"""Node graph (PRD v2 §5, §6): the fixed set of conversation states and which transitions between
them are legal. Pure, no I/O.

The LLM never chooses the next node on its own authority (PRD §5, CLAUDE.md rule 3) — it returns a
`proposed_next` node name as a *suggestion*; `next_node()` below is the only thing that actually
decides, and it refuses (falls back to `current`, logs the rejection) any proposal that isn't a
legal edge from the current node. Policy/safety pre-empts (opt-out, callback, wrong-number,
silence, safety interrupt) bypass this table entirely — they are decided in `policy.py`/`safety.py`
*before* the node LLM is even called, exactly per the PRD §5 step ordering.
"""

from __future__ import annotations

import enum


class Node(enum.StrEnum):
    open_and_identify = "open_and_identify"
    caregiver = "caregiver"
    purpose_consent_time = "purpose_consent_time"
    open_experience = "open_experience"
    overall_rating = "overall_rating"
    probe_topics = "probe_topics"
    complaint_detail = "complaint_detail"
    severity_gate = "severity_gate"
    anything_else = "anything_else"
    readback_and_next_steps = "readback_and_next_steps"
    close = "close"
    # Utility / terminal nodes (PRD §6, "Utility nodes (all FIXED)")
    callback = "callback"
    opt_out = "opt_out"
    close_wrong = "close_wrong"
    escalate_standard = "escalate_standard"
    escalate_urgent = "escalate_urgent"


# Nodes with no outgoing edges — a call ending up here is over. `next_node()` treats any proposal
# from a terminal node as illegal (stays put; the caller must have already ended the call).
TERMINAL_NODES: frozenset[Node] = frozenset(
    {Node.close, Node.callback, Node.opt_out, Node.close_wrong}
)

# The legal-edge table (PRD §6's per-node "Next" columns + §6's utility-node prose + §7.5/§7.4 for
# the two escalation nodes). Every node self-loops onto itself where the PRD describes a repeat/
# continue behaviour (e.g. "kaun bol raha hai" re-asks identity, PROBE_TOPICS keeps probing) —
# encoded explicitly rather than assumed, so an illegal proposal is caught, not silently allowed.
EDGES: dict[Node, frozenset[Node]] = {
    Node.open_and_identify: frozenset(
        {
            Node.open_and_identify,  # "kaun bol raha hai" -> repeat + re-ask (a repair, not a move)
            Node.purpose_consent_time,
            Node.caregiver,
            Node.close_wrong,
            Node.callback,
            Node.opt_out,
        }
    ),
    Node.caregiver: frozenset({Node.purpose_consent_time, Node.callback}),
    Node.purpose_consent_time: frozenset(
        {
            Node.purpose_consent_time,  # "kya aap robot ho?" -> answer + re-ask permission (once)
            Node.open_experience,
            Node.callback,
            Node.opt_out,
            Node.close,  # refuses recording -> fixed line -> close, no_consent outcome
        }
    ),
    Node.open_experience: frozenset({Node.overall_rating, Node.probe_topics}),
    Node.overall_rating: frozenset({Node.probe_topics, Node.anything_else}),
    Node.probe_topics: frozenset(
        {
            Node.probe_topics,
            Node.complaint_detail,
            Node.overall_rating,  # rating not yet asked when the probe loop ends
            Node.anything_else,
        }
    ),
    Node.complaint_detail: frozenset({Node.complaint_detail, Node.severity_gate}),
    Node.severity_gate: frozenset(
        {
            Node.escalate_standard,
            Node.escalate_urgent,
            Node.probe_topics,
            Node.anything_else,
        }
    ),
    Node.anything_else: frozenset(
        {Node.anything_else, Node.complaint_detail, Node.readback_and_next_steps}
    ),
    Node.readback_and_next_steps: frozenset(
        {
            Node.readback_and_next_steps,  # corrects -> re-confirm (max 2, enforced in state)
            Node.complaint_detail,  # patient corrects a complaint's detail
            Node.close,
        }
    ),
    Node.close: frozenset(),
    Node.callback: frozenset(),
    Node.opt_out: frozenset(),
    Node.close_wrong: frozenset(),
    # ESCALATE_STANDARD returns to the normal flow (PRD §7.5); ESCALATE_URGENT never does (§7.4).
    Node.escalate_standard: frozenset({Node.probe_topics, Node.anything_else}),
    Node.escalate_urgent: frozenset({Node.close}),
}


def is_legal_edge(current: Node, proposed: Node) -> bool:
    return proposed in EDGES.get(current, frozenset())


def next_node(current: Node, proposed: Node) -> Node:
    """The one authority over transitions. Returns `proposed` if it's a legal edge from `current`,
    else `current` unchanged (caller logs `ILLEGAL_TRANSITION_PROPOSED` when this happens — see
    `pfa_call_service.py`, which is the one place with DB/event access to log it).
    """
    if current in TERMINAL_NODES:
        return current
    return proposed if is_legal_edge(current, proposed) else current
