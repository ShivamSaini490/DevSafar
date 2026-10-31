# DevSafar Backend - Foundation + Auth/OTP + Chat Modes + LangGraph Slice

Python 3.12 FastAPI foundation with async PostgreSQL, Redis, versioned health routes,
safe error responses, structured redacted logs, Docker, and tests.

Auth uses Argon2id passwords and revocable, short-lived HS256 JWT sessions. The JWT is
sent only in an HttpOnly SameSite=Lax cookie; authenticated writes also require the
double-submit CSRF cookie/header pair. Password-reset OTPs and reset grants are stored
only as keyed hashes. For local development, SMTP-less OTP delivery is skipped only when
`ENVIRONMENT=development` and `DEV_OTP_EMAIL_FALLBACK_ENABLED=true`; the code is never logged.
Forgot-password and resend delivery runs as a FastAPI background task after the generic
response is sent. SMTP failures are warning-only and cannot change the public response.

For SMTP, `SMTP_USE_TLS=true` means implicit TLS and normally pairs with port 465.
`SMTP_USE_TLS=false` means STARTTLS and normally pairs with port 587. Standard ports are
always mapped safely (587 uses `start_tls=True, use_tls=False`; 465 uses
`use_tls=True, start_tls=False`) and an inconsistent setting logs a startup warning.
`SMTP_TIMEOUT_SECONDS` bounds connect and SMTP command waits. When using Gmail, enable
2-Step Verification, set `SMTP_USERNAME` to the full Gmail address, and paste the Gmail
app password into `SMTP_PASSWORD` without spaces.

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

The LangGraph vertical slice runs five nodes in-request: intent, provider research,
deterministic planning, deterministic validation, and response. Groq is used only for
structured intent extraction; dates, durations, budgets, totals, retries, and feasibility
are calculated in Python. Maps, transport, and hotel fallbacks remain clearly labelled
stubs and never emit `live_quote`. Configure `GROQ_MODEL`,
`GROQ_TIMEOUT_SECONDS`, and `GRAPH_TIMEOUT_SECONDS` as needed. Missing or failed Groq
configuration returns a public-safe `503` instead of an internal error.

## Tavily attraction research and booking redirects

Tavily is opt-in with `TAVILY_ENABLED=false` by default. When enabled, set
`TAVILY_API_KEY` in the environment, keep `TAVILY_BASE_URL=https://api.tavily.com`, and
allowlist that exact host with `TAVILY_ALLOWED_HOSTS`. DevSafar sends only a fixed query
containing the destination city, uses Basic search (1 credit per search), caps cache
misses with `TAVILY_MAX_SEARCHES_PER_TRIP` (default 2), and caches each city in Redis for
`TAVILY_CACHE_TTL_SECONDS` (default seven days). Requests have a bounded timeout and at
most one retry. Disabled service, exhausted credits, invalid data, or network failure
falls back to labelled stub attractions without failing the trip.

Tavily web text is treated only as untrusted data. Social/video results configured in
`TAVILY_EXCLUDED_DOMAINS` are removed first. At most
`TAVILY_SNIPPETS_FOR_EXTRACTION` results (default 4) are sent per city, each capped by
`ATTRACTION_SNIPPET_MAX_CHARS` (default 700); duplicate and near-empty snippets are
dropped. Groq structured output proposes named places and verbatim evidence; Python then requires
the normalized name and evidence to exist in the same snippet, rejects page titles,
deduplicates names, and caps results with `ATTRACTIONS_PER_DESTINATION` (default 6).
Only the grounded place objects are cached (`v2` cache key), so a cache hit calls neither
Tavily nor Groq. Failed research is never stored as a successful result; a separate
`TAVILY_NEGATIVE_CACHE_TTL_SECONDS` cache (default 120 seconds) briefly prevents repeated
provider hammering. Extraction failure or zero grounded results returns the labelled
unknown fallback and marks the Tavily data source degraded.

Attraction extraction uses `GROQ_EXTRACTION_MODEL`; leaving it empty reuses `GROQ_MODEL`.
A smaller model can be selected because Python grounding rejects every place that is not
literally supported by the supplied source text. A 429 response is retried at most once
after its `Retry-After`, bounded by `GROQ_MAX_RETRY_WAIT_SECONDS` (default 8). A 400
structured-output failure gets one JSON-object-mode retry followed by local Pydantic and
Python grounding validation. Logs contain only safe diagnostics and external-call counts,
never prompts, snippets, failed generations, or provider keys.

Descriptions are built in Python from the grounded evidence sentence, stripped of HTML,
Markdown, links, emoji, and excess whitespace, then limited to 200 characters. Fees and
opening hours are parsed only from that same sentence; fees remain estimates tied to the
grounding URL and are never live quotes. The frontend must render attraction names,
categories, descriptions, and itinerary notes as plain text only, never as HTML or via an
HTML-injection API.

`booking_links` contains plain HTTPS search/main-page redirects for IRCTC, MakeMyTrip,
redBus, Google Flights, and Booking.com. Transport links are grouped by `leg_index`;
hotel links are grouped by `stay_index` and carry that stay city's check-in/check-out
dates. No affiliate or invented route parameters are added. Every redirect host is checked
against `BOOKING_ALLOWED_HOSTS`; opening one is not a confirmed booking and no price is
implied. Flight links also tell the user to verify the nearest-airport availability.

Road schedules start driving days at 06:00 India time. `MAX_DRIVING_HOURS_PER_DAY`
limits cumulative driving time per calendar day, while `DRIVING_LATEST_ARRIVAL_HOUR`
(default 21) is the clock cutoff. An en-route hotel is added only when a leg actually
crosses an overnight rest boundary.

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

- .env.example must contain only empty or placeholder values. Never copy values from backend/.env.
