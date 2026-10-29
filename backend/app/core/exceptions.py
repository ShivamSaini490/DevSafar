import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.logging import (
    redact_exception_traceback,
    redact_sensitive_data,
    redact_sensitive_text,
)

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


class ServiceUnavailableError(AppError):
    def __init__(self, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            code="service_unavailable",
            message="Service dependencies are not ready.",
            details=details,
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": redact_sensitive_text(message),
        "request_id": _request_id(request),
    }
    if details is not None:
        error["details"] = redact_sensitive_data(details)
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    settings = getattr(request.app.state, "settings", None)
    secret_values = settings.redaction_secret_values() if isinstance(settings, Settings) else ()
    logger.error(
        "Unhandled application error",
        extra={
            "error_type": type(exc).__name__,
            "request_id": _request_id(request),
            "traceback": redact_exception_traceback(exc, secret_values=secret_values),
        },
    )
    return _error_response(
        request,
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="internal_server_error",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            request,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Request validation failed.",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        phrase = (
            HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus else "HTTP error"
        )
        message = str(exc.detail) if exc.status_code < 500 else phrase
        code = phrase.lower().replace(" ", "_")
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return handle_unexpected_exception(request, exc)
