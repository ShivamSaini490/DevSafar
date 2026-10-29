import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "authorization",
    "cookie",
    "email",
    "jwt",
    "otp",
    "passwd",
    "password",
    "secret",
    "token",
)

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
AUTHORIZATION_PATTERN = re.compile(r"(?i)(\bauthorization\b\s*[=:]\s*)(?:Bearer\s+)?[^\s,;]+")
CONNECTION_URL_PATTERN = re.compile(
    r"(?i)\b(?:postgres(?:ql)?(?:\+asyncpg)?|redis(?:\+sentinel)?|rediss)://[^\s'\")]+"
)
KEY_VALUE_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|cookie|email|jwt|otp|passwd|password|secret|token)"
    r"\b\s*[=:]\s*)([^\s,;]+)"
)

STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_sensitive_text(value: str) -> str:
    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    redacted = CONNECTION_URL_PATTERN.sub("[REDACTED_CONNECTION_URL]", redacted)
    redacted = AUTHORIZATION_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
    return KEY_VALUE_PATTERN.sub(r"\1[REDACTED]", redacted)


def redact_sensitive_data(value: Any, *, key: object | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_sensitive_data(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_exception_message(
    exc: BaseException,
    *,
    secret_values: Iterable[str] = (),
) -> str:
    message = redact_sensitive_text(str(exc))
    for secret in secret_values:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        if extras:
            payload.update(redact_sensitive_data(extras))
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=True)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
