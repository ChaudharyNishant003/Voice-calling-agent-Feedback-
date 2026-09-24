"""Password strength policy (docs/06_ERROR_HANDLING_AND_MESSAGES.md PFA-AUTH-007,
docs/07_SECURITY_AND_COMPLIANCE.md §2 — "min 12 chars, zxcvbn >= 3"). Pure — no I/O; `zxcvbn` is a
deterministic, CPU-only scoring library, not a vendor adapter the import-linter contract restricts.
"""

from __future__ import annotations

from dataclasses import dataclass

import zxcvbn

MIN_LENGTH = 12
MIN_ZXCVBN_SCORE = 3


@dataclass(frozen=True)
class PasswordPolicyResult:
    ok: bool
    reasons: tuple[str, ...]


def validate(password: str) -> PasswordPolicyResult:
    reasons: list[str] = []

    if len(password) < MIN_LENGTH:
        reasons.append(f"must be at least {MIN_LENGTH} characters")

    score = zxcvbn.zxcvbn(password)["score"]
    if score < MIN_ZXCVBN_SCORE:
        reasons.append(f"too weak (zxcvbn score {score}, need >= {MIN_ZXCVBN_SCORE})")

    return PasswordPolicyResult(ok=not reasons, reasons=tuple(reasons))
