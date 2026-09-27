"""Deterministic assertions for a finished scenario call (PRD v2 Phase 7 §13.4-style hard gates).

Checks the last `TurnApiResult` (node/ended/outcome/escalated) plus `pfa_results_service`'s read
side (rating/complaints/escalations/respondent_type) against a scenario's `expect` block. Every key
is optional; only the keys a scenario declares are checked. Returns a list of human-readable failure
strings — empty means the scenario passed its deterministic gate.
"""

from __future__ import annotations

from app.services.pfa_call_service import TurnApiResult
from app.services.pfa_results_service import ResultDetail

_SEVERITY_ORDER = ["S0", "S1", "S2", "S3", "S4"]


def _severity_max(complaints: list[dict[str, object]]) -> str | None:
    present = [c["severity"] for c in complaints if c.get("severity")]
    if not present:
        return None
    return max(present, key=_SEVERITY_ORDER.index)  # type: ignore[arg-type]


def check_expectations(
    *, expect: dict[str, object], last_result: TurnApiResult, detail: ResultDetail
) -> list[str]:
    failures: list[str] = []

    def _mismatch(label: str, expected: object, actual: object) -> None:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    if not last_result.ended:
        failures.append("call did not end within the scenario's declared turns")

    if "final_node" in expect and last_result.node != expect["final_node"]:
        _mismatch("final_node", expect["final_node"], last_result.node)

    if "outcome" in expect and last_result.call_outcome != expect["outcome"]:
        _mismatch("outcome", expect["outcome"], last_result.call_outcome)

    if "escalated" in expect and last_result.escalated != expect["escalated"]:
        _mismatch("escalated", expect["escalated"], last_result.escalated)

    if "respondent_type" in expect and detail.respondent_type != expect["respondent_type"]:
        _mismatch("respondent_type", expect["respondent_type"], detail.respondent_type)

    if "rating" in expect and detail.rating != expect["rating"]:
        _mismatch("rating", expect["rating"], detail.rating)

    if "min_rating" in expect:
        min_rating = expect["min_rating"]
        assert isinstance(min_rating, int)
        if detail.rating is None or detail.rating < min_rating:
            _mismatch("min_rating", f">= {min_rating}", detail.rating)

    if "complaint_count" in expect and len(detail.complaints) != expect["complaint_count"]:
        _mismatch("complaint_count", expect["complaint_count"], len(detail.complaints))

    if "min_complaint_count" in expect:
        min_count = expect["min_complaint_count"]
        assert isinstance(min_count, int)
        if len(detail.complaints) < min_count:
            _mismatch("min_complaint_count", f">= {min_count}", len(detail.complaints))

    if "escalation_count" in expect and len(detail.escalations) != expect["escalation_count"]:
        _mismatch("escalation_count", expect["escalation_count"], len(detail.escalations))

    if "min_escalation_count" in expect:
        min_count = expect["min_escalation_count"]
        assert isinstance(min_count, int)
        if len(detail.escalations) < min_count:
            _mismatch("min_escalation_count", f">= {min_count}", len(detail.escalations))

    if "topic_count" in expect and len(detail.topics) != expect["topic_count"]:
        _mismatch("topic_count", expect["topic_count"], len(detail.topics))

    if "min_topic_count" in expect:
        min_count = expect["min_topic_count"]
        assert isinstance(min_count, int)
        if len(detail.topics) < min_count:
            _mismatch("min_topic_count", f">= {min_count}", len(detail.topics))

    if "language_mode" in expect and detail.language_mode != expect["language_mode"]:
        _mismatch("language_mode", expect["language_mode"], detail.language_mode)

    if "severity_max" in expect:
        actual = _severity_max(detail.complaints) or _severity_max(
            [{"severity": e["severity"]} for e in detail.escalations]
        )
        if actual != expect["severity_max"]:
            _mismatch("severity_max", expect["severity_max"], actual)

    return failures
