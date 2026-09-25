"""All ORM models, imported here so `Base.metadata` is fully populated for Alembic."""

from app.db.base import Base
from app.db.models.auth import RefreshToken
from app.db.models.calls import Call, CallEvent, SurveyResponse, Transcript
from app.db.models.cases import Case, CaseEvent, Complaint
from app.db.models.compliance import (
    AccountEncryptionKey,
    AuditLogEntry,
    DeletionRequest,
    PendingSafetyCase,
    SuppressionEntry,
)
from app.db.models.demo import DemoSettings, ProviderCredential
from app.db.models.ingestion import IngestionBatch, IngestionRowError
from app.db.models.patients_visits import Patient, Visit
from app.db.models.platform import CostRate, FeatureFlag
from app.db.models.survey import SurveyVersion
from app.db.models.tenancy import Account, Department, Location, User

__all__ = [
    "Account",
    "AccountEncryptionKey",
    "AuditLogEntry",
    "Base",
    "Call",
    "CallEvent",
    "Case",
    "CaseEvent",
    "Complaint",
    "CostRate",
    "DeletionRequest",
    "DemoSettings",
    "Department",
    "FeatureFlag",
    "IngestionBatch",
    "IngestionRowError",
    "Location",
    "Patient",
    "PendingSafetyCase",
    "ProviderCredential",
    "RefreshToken",
    "SuppressionEntry",
    "SurveyResponse",
    "SurveyVersion",
    "Transcript",
    "User",
    "Visit",
]
