"""Canonical business vocabulary (docs/02_DATA_MODEL.md §1) — pure, zero imports beyond stdlib.

Lives in `domain` (not `db.models`) so pure domain modules (`domain/eligibility.py`, etc.) can use
this vocabulary without violating the domain-purity import-linter contract, which forbids
`app.domain` from importing `app.db`. `app.db.models.enums` re-exports these for the ORM layer
instead of defining its own copy, so persisted values and domain values are always the same objects.
"""

from __future__ import annotations

import enum


class AccountStatus(enum.StrEnum):
    onboarding = "onboarding"
    live = "live"
    paused = "paused"
    offboarded = "offboarded"


class VisitType(enum.StrEnum):
    outpatient = "outpatient"
    diagnostic = "diagnostic"


class EligibilityStatus(enum.StrEnum):
    pending = "pending"
    eligible = "eligible"
    suppressed = "suppressed"
    review = "review"


class SuppressionReason(enum.StrEnum):
    minor = "minor"
    invalid_number = "invalid_number"
    opt_out = "opt_out"
    dnd = "dnd"
    duplicate_encounter = "duplicate_encounter"
    already_called_visit = "already_called_visit"
    frequency_cap = "frequency_cap"
    stale_visit = "stale_visit"
    shared_number_review = "shared_number_review"
    consent_declined_visit = "consent_declined_visit"
    out_of_scope_visit_type = "out_of_scope_visit_type"
    missing_required_field = "missing_required_field"
    deleted_patient = "deleted_patient"


class CallStatus(enum.StrEnum):
    queued = "queued"
    dialing = "dialing"
    ringing = "ringing"
    answered = "answered"
    in_progress = "in_progress"
    completed = "completed"
    partial = "partial"
    abandoned_pre_consent = "abandoned_pre_consent"
    consent_declined = "consent_declined"
    voicemail = "voicemail"
    no_answer = "no_answer"
    busy = "busy"
    failed_telephony = "failed_telephony"
    failed_system = "failed_system"
    cancelled = "cancelled"


class ConsentState(enum.StrEnum):
    not_asked = "not_asked"
    granted = "granted"
    declined = "declined"
    withdrawn = "withdrawn"
    granted_unrecorded = "granted_unrecorded"


class RespondentType(enum.StrEnum):
    patient = "patient"
    proxy = "proxy"
    unknown = "unknown"


class CampaignType(enum.StrEnum):
    service_feedback = "service_feedback"
    promotional = "promotional"


class Sentiment(enum.StrEnum):
    negative = "negative"
    neutral = "neutral"
    positive = "positive"


class Urgency(enum.StrEnum):
    routine = "routine"
    service_failure = "service_failure"
    safety_concern = "safety_concern"


class CaseStatus(enum.StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    assigned = "assigned"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"
    reopened = "reopened"
    merged = "merged"
    invalid = "invalid"


class CasePriority(enum.StrEnum):
    p1 = "p1"
    p2 = "p2"
    p3 = "p3"


class UserRole(enum.StrEnum):
    super_admin = "super_admin"
    admin = "admin"
    quality = "quality"
    dept_owner = "dept_owner"
    read_only = "read_only"


class Speaker(enum.StrEnum):
    agent = "agent"
    patient = "patient"
    system = "system"


class DeletionScope(enum.StrEnum):
    patient = "patient"
    account = "account"


class DeletionStatus(enum.StrEnum):
    requested = "requested"
    approved = "approved"
    running = "running"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"


class IngestionStatus(enum.StrEnum):
    received = "received"
    validating = "validating"
    validated = "validated"
    failed = "failed"
    processed = "processed"
