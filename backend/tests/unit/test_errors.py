from app.core.errors import (
    AdapterAuthError,
    AdapterError,
    ComplianceBlock,
    ConflictError,
    DependencyError,
    NotFoundError,
    PFAError,
    ValidationError,
    error_envelope,
)


def test_error_envelope_shape() -> None:
    err = ValidationError(
        "PFA-ING-001", message="Please upload a .csv file.", details={"field": "file"}
    )
    envelope = error_envelope(err, request_id="req_test123")

    assert envelope == {
        "error": {
            "code": "PFA-ING-001",
            "message": "Please upload a .csv file.",
            "details": {"field": "file"},
            "request_id": "req_test123",
        }
    }


def test_http_status_mapping() -> None:
    assert ValidationError("X").http_status == 422
    assert NotFoundError("X").http_status == 404
    assert ConflictError("X").http_status == 409
    assert DependencyError("X").http_status == 503
    assert ComplianceBlock("X").http_status == 409


def test_dependency_errors_default_retryable() -> None:
    assert DependencyError("X").retryable is True
    assert AdapterError("X").retryable is True


def test_adapter_auth_error_not_retryable() -> None:
    assert AdapterAuthError("X").retryable is False


def test_error_details_default_empty_dict() -> None:
    err = PFAError("PFA-SYS-001")
    assert err.details == {}
    assert err.message == "PFA-SYS-001"
