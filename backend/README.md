# DevSafar Backend - Foundation + Auth/OTP + Chat Modes + LangGraph Slice

Python 3.12 FastAPI foundation with async PostgreSQL, Redis, versioned health routes,
safe error responses, structured redacted logs, Docker, and tests.

Auth uses Argon2id passwords and revocable, short-lived HS256 JWT sessions. The JWT is
sent only in an HttpOnly SameSite=Lax cookie; authenticated writes also require the
double-submit CSRF cookie/header pair. Password-reset OTPs and reset grants are stored
only as keyed hashes. For local development, SMTP-less OTP delivery is skipped only when
`ENVIRONMENT=development` and `DEV_OTP_EMAIL_FALLBACK_ENABLED=true`; the code is never logged.

Set a persistent, random `SECRET_KEY` in the local environment for stable development
sessions. If it is absent only in `development`, the app generates a process-local key and
logs a warning; all sessions then become invalid after restart. Staging and production
still refuse to start without an explicitly configured key.

Saved conversations are available only to authenticated owners. Their expiry is fixed
at creation time plus seven days and is never refreshed by activity; every chat and
message query also rejects expired records before scheduled cleanup runs.

Temporary chat stores only bounded Redis context for 30 minutes (refreshed per turn) and
never creates PostgreSQL rows or LangSmith traces. On the first turn the API returns an
opaque `temp_token` response field. The frontend must keep that token and its random
`temp_session_id` only in tab memory and send both on later turns. A cookie is deliberately
not used because cookies are shared across browser tabs; the Redis key is an HMAC of both
values, and neither raw value is used as a key or logged. The endpoint returns the clearly
labelled structured trip response from the same in-request graph. Temporary results and
follow-up context stay only in bounded Redis state and never create trip or itinerary rows.

The LangGraph vertical slice runs five nodes in-request: intent, stub research,
deterministic planning, deterministic validation, and response. Groq is used only for
structured intent extraction; dates, durations, budgets, totals, retries, and feasibility
are calculated in Python. Maps, transport, hotel, and places integrations are clearly
labelled stubs and never emit `live_quote`. Configure `GROQ_MODEL`,
`GROQ_TIMEOUT_SECONDS`, and `GRAPH_TIMEOUT_SECONDS` as needed. Missing or failed Groq
configuration returns a public-safe `503` instead of an internal error.

Saved chat turns persist the strict `TripResponse` and a versioned itinerary in PostgreSQL.
`GET /api/v1/trips/{trip_id}` enforces the same owner and unexpired-conversation rules as
chat retrieval. The graph currently has no checkpointer; saved-only checkpointing is
deferred, and temporary chats must never create checkpoints.

Expired-chat cleanup runs from the FastAPI lifespan every 15 minutes by default. It can be
configured with `CLEANUP_INTERVAL_SECONDS` and `CLEANUP_BATCH_SIZE`, or disabled with
`CLEANUP_ENABLED=false` (the integration test app does this explicitly).

## Local setup

1. Copy `backend/.env.example` to a local, untracked `backend/.env` and replace the
   placeholders. Settings load that exact backend path regardless of the shell's current
   directory; exported environment variables take precedence.
2. Start local dependencies from the repository root:

   ```powershell
   docker compose up -d postgres redis
   ```

3. From `backend/`, install the generated requirements and run the API:

   ```powershell
   python -m pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

   Apply migrations before starting the API; tables are never created with `create_all`:

   ```powershell
   alembic upgrade head
   ```

4. Verify:

   ```text
   GET http://127.0.0.1:8000/api/v1/health
   GET http://127.0.0.1:8000/api/v1/ready
   ```

`/health` proves the API process is alive. `/ready` returns ready only when PostgreSQL
and Redis respond successfully. Groq, Qdrant, SMTP, and LangSmith are intentionally not
part of readiness.

## Quality checks

Auth/OTP integration tests require a real PostgreSQL database named `devsafar_test`.
Export `TEST_DATABASE_URL` in the test process; the test suite deliberately does not load
`backend/.env`. `TEST_REDIS_URL` is optional and defaults to local Redis database 15.

```powershell
ruff check .
mypy app
pytest
```

## Tracing and sensitive data

LangSmith tracing defaults to off and is enabled only when `LANGSMITH_TRACING=true`, a
LangSmith key exists, and the run is a saved chat. Temporary execution explicitly disables
tracing at graph invocation. Trace tags contain only `saved_chat`; metadata contains only
the opaque conversation ID, while input/output masking hooks replace traced payloads.
Application logs use the existing redaction rules and never include user prompts or raw
secrets in planning-failure diagnostics.
