"""Run a destructive, self-cleaning API smoke test against a running DevSafar API."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import httpx

GENERIC_FORGOT_MESSAGE = "If an account exists, a password reset code has been sent."
CANONICAL_TRIP_FIELDS = {
    "route_legs",
    "hotels",
    "attractions",
    "itinerary_days",
    "transport_options",
    "booking_links",
    "data_sources",
}


class SmokeFailure(RuntimeError):
    """A public-safe smoke assertion failure."""


def _error_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        return "non_json_response"
    if not isinstance(body, dict):
        return "unexpected_response"
    error = body.get("error")
    if not isinstance(error, dict):
        return "unexpected_response"
    code = error.get("code")
    return str(code) if code else "unexpected_response"


def _expect_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise SmokeFailure(
            f"expected HTTP {expected}, received HTTP {response.status_code} "
            f"({_error_code(response)})"
        )


def _step[T](name: str, operation: Callable[[], T]) -> T:
    try:
        result = operation()
    except Exception as exc:
        message = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
        print(f"FAIL {name}: {message}")
        raise
    print(f"PASS {name}")
    return result


def _csrf_headers(client: httpx.Client) -> dict[str, str]:
    csrf = client.cookies.get("csrf_token")
    if not csrf:
        raise SmokeFailure("CSRF cookie was not issued")
    return {"X-CSRF-Token": csrf}


def _terminal_sse_event(
    client: httpx.Client,
    events_url: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    with client.stream("GET", events_url, params=params) as response:
        _expect_status(response, 200)
        data_lines: list[str] = []
        for line in response.iter_lines():
            if line == "":
                if not data_lines:
                    continue
                event = json.loads("\n".join(data_lines))
                data_lines.clear()
                if isinstance(event, dict) and event.get("event") in {"completed", "failed"}:
                    if event["event"] == "failed":
                        raise SmokeFailure(f"planning stream failed ({event.get('code', 'unknown')})")
                    return event
                continue
            if line.startswith("data: "):
                data_lines.append(line[6:])
    raise SmokeFailure("planning stream ended without a completed event")


def _assert_trip_shape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SmokeFailure("trip response is not a JSON object")
    missing = sorted(CANONICAL_TRIP_FIELDS - payload.keys())
    if missing:
        raise SmokeFailure(f"trip response is missing fields: {', '.join(missing)}")
    if payload.get("status") not in {"completed", "needs_clarification"}:
        raise SmokeFailure("trip response has an unexpected status")
    if not isinstance(payload.get("data_sources"), list):
        raise SmokeFailure("data_sources is not a list")
    return payload


def _trip_prompt() -> str:
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=3)
    return (
        "Plan a road trip from Hyderabad to Puducherry and back for one traveler "
        f"from {start.isoformat()} to {end.isoformat()} with a budget of INR 30000."
    )


def _cleanup_account(
    client: httpx.Client,
    *,
    email: str,
    password: str,
) -> None:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    _expect_status(login, 200)
    deleted = client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": password},
        headers=_csrf_headers(client),
    )
    _expect_status(deleted, 200)


def _run(base_url: str) -> int:
    email = f"devsafar-smoke-{uuid4().hex}@example.com"
    password = f"A-{secrets.token_urlsafe(24)}"
    signup_payload = {
        "name": "DevSafar Smoke",
        "email": email,
        "password": password,
        "confirm_password": password,
    }
    timeout = httpx.Timeout(150.0, connect=10.0)
    account_created = False
    account_deleted = False
    failed = False

    with httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=False) as client:
        try:
            _step("health", lambda: _expect_status(client.get("/api/v1/health"), 200))
            _step("ready", lambda: _expect_status(client.get("/api/v1/ready"), 200))

            def signup() -> None:
                nonlocal account_created
                _expect_status(client.post("/api/v1/auth/signup", json=signup_payload), 201)
                account_created = True

            _step("signup", signup)

            def login() -> None:
                response = client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": password},
                )
                _expect_status(response, 200)
                body = response.json()
                if isinstance(body, dict) and any(
                    key in body for key in ("access_token", "token", "jwt")
                ):
                    raise SmokeFailure("login JSON exposed a token")
                if not client.cookies.get("access_token"):
                    raise SmokeFailure("login did not issue an access cookie")

            _step("login", login)
            _step("users/me", lambda: _expect_status(client.get("/api/v1/users/me"), 200))

            def create_conversation() -> str:
                response = client.post(
                    "/api/v1/conversations",
                    json={"title": "Smoke trip"},
                    headers=_csrf_headers(client),
                )
                _expect_status(response, 201)
                return str(response.json()["id"])

            conversation_id = _step("create saved chat", create_conversation)
            prompt = _trip_prompt()

            def start_saved_async() -> dict[str, Any]:
                response = client.post(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    params={"async": "true"},
                    json={"content": prompt},
                    headers=_csrf_headers(client),
                )
                _expect_status(response, 202)
                body = response.json()
                if not isinstance(body, dict):
                    raise SmokeFailure("async planning response is not an object")
                return body

            saved_async = _step("start saved async planning", start_saved_async)
            _step(
                "saved SSE completed",
                lambda: _terminal_sse_event(client, str(saved_async["events_url"])),
            )

            def fetch_trip() -> None:
                response = client.get(f"/api/v1/trips/{saved_async['trip_id']}")
                _expect_status(response, 200)
                _assert_trip_shape(response.json())

            _step("fetch saved trip", fetch_trip)

            def sync_plan() -> None:
                response = client.post(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    json={"content": "Keep the same route and reduce optional stops."},
                    headers=_csrf_headers(client),
                )
                _expect_status(response, 201)
                _assert_trip_shape(response.json().get("trip"))

            _step("sync planning", sync_plan)

            def temporary_async() -> None:
                with httpx.Client(
                    base_url=base_url,
                    timeout=timeout,
                    follow_redirects=False,
                ) as guest:
                    session_id = secrets.token_urlsafe(32)
                    started = guest.post(
                        "/api/v1/chat/temporary",
                        params={"async": "true"},
                        json={"temp_session_id": session_id, "content": prompt},
                    )
                    _expect_status(started, 202)
                    body = started.json()
                    token = body.get("temp_token")
                    if not isinstance(token, str) or not token:
                        raise SmokeFailure("temporary chat did not issue a token")
                    terminal = _terminal_sse_event(
                        guest,
                        str(body["events_url"]),
                        params={"temp_session_id": session_id, "temp_token": token},
                    )
                    _assert_trip_shape(terminal.get("trip"))

            _step("temporary async planning", temporary_async)

            def forgot_password() -> None:
                response = client.post("/api/v1/auth/forgot-password", json={"email": email})
                _expect_status(response, 200)
                if response.json().get("message") != GENERIC_FORGOT_MESSAGE:
                    raise SmokeFailure("forgot-password response was not generic")

            _step("forgot-password generic response", forgot_password)
            _step(
                "logout",
                lambda: _expect_status(
                    client.post("/api/v1/auth/logout", headers=_csrf_headers(client)),
                    200,
                ),
            )
        except Exception:
            failed = True
        finally:
            if account_created and not account_deleted:
                try:
                    _step(
                        "cleanup account",
                        lambda: _cleanup_account(client, email=email, password=password),
                    )
                    account_deleted = True
                except Exception:
                    failed = True
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Running API base URL (default: http://127.0.0.1:8000)",
    )
    return parser


def main(argv: Iterator[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    return _run(str(args.base_url).rstrip("/"))


if __name__ == "__main__":
    sys.exit(main())
