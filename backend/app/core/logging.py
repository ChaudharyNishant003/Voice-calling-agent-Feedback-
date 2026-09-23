"""Structured JSON logging via structlog, with a mandatory redaction processor.

CLAUDE.md §4 rule 10 / doc 06 §1.5: never log phone numbers, transcripts, or audio URLs in plain
text. The redaction processor below is applied to every log record — including ones destined for
Sentry (core.observability wires it in there too) — so there is exactly one place this rule lives.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog
from structlog.types import EventDict, Processor

# Candidate digit-ish runs (phone numbers, but also ISO timestamp fragments like "2026-09-23").
# A separate digit-count check below (>=9 actual digits) tells the two apart, since a date has
# few digits padded out by separators while a phone number is almost all digits.
_PHONE_CANDIDATE_RE = re.compile(r"\+?\d[\d\-\s]{6,16}\d")
_MIN_PHONE_DIGITS = 9
_SENSITIVE_KEYS = {
    "phone",
    "phone_number",
    "to_e164",
    "from_e164",
    "raw_phone",
    "transcript",
    "transcript_text",
    "text",
    "utterance_text",
    "audio_url",
    "recording_url",
}
_REDACTED = "[REDACTED]"


def _mask_phone_like(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        digit_count = sum(1 for c in match.group(0) if c.isdigit())
        return _REDACTED if digit_count >= _MIN_PHONE_DIGITS else match.group(0)

    return _PHONE_CANDIDATE_RE.sub(_replace, text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _mask_phone_like(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(v) for v in value)
    return value


def redaction_processor(logger: object, method_name: str, event_dict: EventDict) -> EventDict:
    """Drop known-sensitive keys entirely; regex-mask phone-shaped substrings everywhere else."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(*, json: bool = True, level: int = logging.INFO) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redaction_processor,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(*args: object, **kwargs: object) -> structlog.types.FilteringBoundLogger:
    """Bind call_id/case_id/account_id when known (CLAUDE.md §8), e.g. get_logger(call_id=x)."""
    logger: structlog.types.FilteringBoundLogger = structlog.get_logger(*args, **kwargs)
    return logger
