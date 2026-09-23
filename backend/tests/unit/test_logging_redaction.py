import io
import json
import logging
from typing import Any

import structlog

from app.core.logging import configure_logging


def _capture_json_log(**event_kwargs: object) -> dict[str, Any]:
    buffer = io.StringIO()
    configure_logging(json=True, level=logging.INFO)
    structlog.configure(
        processors=structlog.get_config()["processors"],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=buffer),
        cache_logger_on_first_use=False,
    )
    logger = structlog.get_logger()
    logger.info("event", **event_kwargs)
    result: dict[str, Any] = json.loads(buffer.getvalue().strip())
    return result


def test_sensitive_keys_are_redacted() -> None:
    record = _capture_json_log(
        phone="+919876543210",
        transcript="patient said the injection hurt",
        audio_url="https://s3.example/audio/call_1.wav",
    )
    assert record["phone"] == "[REDACTED]"
    assert record["transcript"] == "[REDACTED]"
    assert record["audio_url"] == "[REDACTED]"


def test_phone_shaped_substrings_are_masked_in_free_text() -> None:
    record = _capture_json_log(message="called +91 98765 43210 about the visit")
    assert "98765" not in record["message"]
    assert "[REDACTED]" in record["message"]


def test_nested_structures_are_redacted() -> None:
    record = _capture_json_log(details={"phone": "+919876543210", "reason": "no_answer"})
    assert record["details"]["phone"] == "[REDACTED]"
    assert record["details"]["reason"] == "no_answer"


def test_non_sensitive_fields_pass_through() -> None:
    record = _capture_json_log(call_id="call_abc123", outcome="answered")
    assert record["call_id"] == "call_abc123"
    assert record["outcome"] == "answered"


def test_iso_timestamps_are_not_mistaken_for_phone_numbers() -> None:
    # Regression: an early version of the phone regex matched "2026-09-23" (date-shaped digit
    # runs), which redacted every log record's own timestamp field.
    record = _capture_json_log(note="deployed at 2026-09-23T17:20:12.122490Z")
    assert "2026-09-23" in record["note"]
    assert record["timestamp"] != "[REDACTED]"
