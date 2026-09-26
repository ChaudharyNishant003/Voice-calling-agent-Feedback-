"""Safety interrupt (PRD v2 §7.2, "Node 0 — global"): a lexicon scan on the patient's normalised
text, OR-merged with the LLM's own `safety.flag` — never AND (a keyword match escalates even if the
LLM disagrees; an LLM flag escalates even with no keyword hit). Runs pre- and post-LLM every turn.

Loading `safety_lexicon.yaml` from disk is the one "impure" thing here, but it's a static asset
read with no external state/network/randomness (same rationale as `scripts.py`'s template loader) —
functionally still pure: same input text always yields the same match. Doesn't violate the
import-linter's domain-purity contract, which is about which *modules* domain code imports
(adapters/services/api/db/workers/agent), not about reading a bundled YAML file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.domain.conversation_graph.state import SafetyCategory

_ASSETS_DIR = Path(__file__).parent / "assets"


@lru_cache(maxsize=1)
def _compiled_lexicon() -> dict[SafetyCategory, list[re.Pattern[str]]]:
    # Boundaries are whitespace-based, not `\b` (=\w-based): Python's `\w` excludes Devanagari
    # combining vowel signs (category Mc, e.g. the ा matra in "मरना"), so `\b` incorrectly splits
    # mid-word for any Hindi word ending in a matra — verified this silently broke self_harm/threat
    # lexicon entries. `(?<!\S)...(?!\S)` only checks for surrounding whitespace/string edges.
    raw = yaml.safe_load((_ASSETS_DIR / "safety_lexicon.yaml").read_text(encoding="utf-8"))
    return {
        SafetyCategory(category): [
            re.compile(rf"(?<!\S)(?:{p})(?!\S)", re.IGNORECASE) for p in patterns
        ]
        for category, patterns in raw.items()
    }


@dataclass(frozen=True)
class SafetyResult:
    triggered: bool
    category: SafetyCategory
    triggered_by: str  # "keyword" | "llm" | "both" | "none"


def scan_lexicon(patient_text: str) -> SafetyCategory | None:
    for category, patterns in _compiled_lexicon().items():
        if any(p.search(patient_text) for p in patterns):
            return category
    return None


def evaluate_safety(
    *,
    patient_text: str,
    llm_flag: bool,
    llm_category: SafetyCategory,
) -> SafetyResult:
    """OR logic (PRD §7.2): a hit from either source triggers, regardless of the other's confidence
    or absence. Keyword category wins when both fire and disagree — lexicon entries are curated and
    high-precision by design, more trustworthy than a single LLM classification.
    """
    keyword_category = scan_lexicon(patient_text)
    keyword_hit = keyword_category is not None
    llm_hit = llm_flag and llm_category != SafetyCategory.none

    if keyword_hit and llm_hit:
        category = keyword_category if keyword_category is not None else llm_category
        return SafetyResult(triggered=True, category=category, triggered_by="both")
    if keyword_hit and keyword_category is not None:
        return SafetyResult(triggered=True, category=keyword_category, triggered_by="keyword")
    if llm_hit:
        return SafetyResult(triggered=True, category=llm_category, triggered_by="llm")
    return SafetyResult(triggered=False, category=SafetyCategory.none, triggered_by="none")
