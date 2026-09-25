"""PFAError hierarchy (docs/06_ERROR_HANDLING_AND_MESSAGES.md §2).

Every raised error has a stable `PFA-<AREA>-<NNN>` code (see doc 06 §4 for the catalogue). Business
code raises these; it never raises bare exceptions or catches-and-ignores (CLAUDE.md §5). Adapters
translate vendor exceptions into `AdapterError` subclasses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse


class PFAError(Exception):
    """Base for every application error. `code` is stable forever — never reused."""

    http_status: int = 500
    user_message_key: str = "err.unexpected"
    retryable: bool = False

    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        details: dict[str, object] | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.code = code
        self.message = message or code
        self.details = details or {}
        self.__cause__ = cause
        super().__init__(self.message)


class ValidationError(PFAError):
    http_status = 422


class PayloadTooLargeError(PFAError):
    http_status = 413


class AuthError(PFAError):
    http_status = 401


class PermissionError_(PFAError):
    http_status = 403


class NotFoundError(PFAError):
    http_status = 404


class ConflictError(PFAError):
    http_status = 409


class RateLimitError(PFAError):
    http_status = 429


class DependencyError(PFAError):
    http_status = 503
    retryable = True


class ComplianceBlock(PFAError):
    """Action blocked by a deterministic compliance rule (consent, opt-out, contact window, …)."""

    http_status = 409


class AdapterError(DependencyError):
    """Base for all vendor/adapter failures. Adapters never leak vendor exceptions past this."""


class AdapterTimeout(AdapterError):
    http_status = 504


class AdapterBadResponse(AdapterError):
    http_status = 502


class AdapterAuthError(AdapterError):
    http_status = 401
    retryable = False


class AdapterRateLimited(AdapterError):
    http_status = 429


def error_envelope(error: PFAError, request_id: str) -> dict[str, object]:
    """Render the envelope from doc 04 §1 — the only shape errors are ever returned in."""
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "request_id": request_id,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register the FastAPI exception handler that renders every PFAError as the doc-04 envelope."""
    from fastapi.responses import JSONResponse

    from app.core.ids import new_id

    @app.exception_handler(PFAError)
    async def _handle_pfa_error(request: Request, exc: PFAError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or new_id("req")
        return JSONResponse(status_code=exc.http_status, content=error_envelope(exc, request_id))
