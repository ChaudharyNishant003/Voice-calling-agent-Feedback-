"""Per-node LLM prompt loader (PRD v2 §5 step 3, §8): loads the static markdown guidance for each
node from `assets/node_prompts/*.md`. Pure, no I/O beyond reading a bundled text file (same
rationale as `scripts.py`/`safety.py`) — building the actual system instruction sent to the LLM
adapter (global rules + persona + state summary + this text) is a services concern and lives in
`services/pfa_call_prompts.py`.

Only nodes where the LLM genuinely interprets patient intent have a prompt file. Pure-FIXED
terminal/utility nodes (close, callback, opt_out, close_wrong, escalate_*, severity_gate) never
call the node LLM at all — `pfa_call_service.py` handles them deterministically.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from app.domain.conversation_graph.graph import Node

_ASSETS_DIR = Path(__file__).parent / "assets" / "node_prompts"

# Nodes with a prompt file — every other node is FIXED-only and never reaches this loader.
_PROMPT_NODES: frozenset[Node] = frozenset(
    {
        Node.open_and_identify,
        Node.caregiver,
        Node.purpose_consent_time,
        Node.open_experience,
        Node.overall_rating,
        Node.probe_topics,
        Node.complaint_detail,
        Node.anything_else,
        Node.readback_and_next_steps,
    }
)


@cache
def load_node_prompt(node: Node) -> str:
    if node not in _PROMPT_NODES:
        raise KeyError(f"node {node!r} has no LLM prompt file (it is FIXED-only)")
    return (_ASSETS_DIR / f"{node.value}.md").read_text(encoding="utf-8")


def has_node_prompt(node: Node) -> bool:
    return node in _PROMPT_NODES
