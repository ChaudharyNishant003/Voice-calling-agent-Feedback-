from app.core.errors import (
    AdapterAuthError,
    AdapterBadResponse,
    AdapterError,
    AdapterRateLimited,
    AdapterTimeout,
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


def test_adapter_error_http_status_mapping() -> None:
    """Each subclass overrides `DependencyError`'s 503 default per its own documented status
    (docs/06_ERROR_HANDLING_AND_MESSAGES.md's PFA-DEMO-00x rows) — previously unenforced, every one
    of these silently fell back to 503 no matter what the doc promised, undetected because every
    call site that could raise one also caught it before it reached the HTTP layer. The Playground
    (docs/11_BUILD_PLAN.md's Demo MVP section) was the first code path to let one propagate all the
    way to a real response, which is how this was actually found.
    """
    assert AdapterAuthError("X").http_status == 401
    assert AdapterBadResponse("X").http_status == 502
    assert AdapterTimeout("X").http_status == 504
    assert AdapterRateLimited("X").http_status == 429


def test_dependency_errors_default_retryable() -> None:
    assert DependencyError("X").retryable is True
    assert AdapterError("X").retryable is True


def test_adapter_auth_error_not_retryable() -> None:
    assert AdapterAuthError("X").retryable is False


def test_error_details_default_empty_dict() -> None:
    err = PFAError("PFA-SYS-001")
    assert err.details == {}
    assert err.message == "PFA-SYS-001"
