# DevSafar Backend

DevSafar is a Python 3.12 FastAPI service for authenticated saved chats, tab-bound
temporary chats, LangGraph trip planning, source-aware travel results, Redis-backed
limits/streams, and seven-day data retention.

The architecture sources are [Backend.pdf](../docs/Backend.pdf),
[Complete.pdf](../docs/Complete.pdf), and [Work Flow.pdf](../docs/Work%20Flow.pdf).

## Prerequisites

- Python 3.12
- PostgreSQL 16
- Redis 7
- Docker Compose v2 (optional)

Do not commit local environment files or secrets. Copy the placeholder template and fill
the local copy from a secrets manager or developer-only source:

```powershell
Copy-Item .env.example .env
docker compose -f ..\docker-compose.yml up -d postgres redis
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The application reads `backend/.env` only outside tests. Exported environment variables
take precedence. Staging and production refuse to start without `SECRET_KEY`.

## Environment variables

The table intentionally lists names only. `.env.example` contains safe placeholders and
comments; real values belong outside version control.

| Area | Variable names |
|---|---|
| Application | `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `DEBUG`, `LOG_LEVEL`, `SECRET_KEY`, `ACCESS_TOKEN_MINUTES`, `ACCESS_TOKEN_COOKIE_NAME`, `CSRF_COOKIE_NAME`, `CORS_ALLOWED_ORIGINS`, `MAX_REQUEST_BODY_BYTES` |
| PostgreSQL | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| Redis | `REDIS_URL` |
| Groq and graph | `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_EXTRACTION_MODEL`, `GROQ_EXTRACTION_FALLBACK_MODEL`, `GROQ_TIMEOUT_SECONDS`, `GROQ_MAX_RETRY_WAIT_SECONDS`, `GRAPH_TIMEOUT_SECONDS` |
| Maps | `MAPS_PROVIDER`, `OSRM_BASE_URL`, `NOMINATIM_BASE_URL`, `NOMINATIM_USER_AGENT`, `NOMINATIM_COUNTRY_CODE`, `MAPS_ALLOWED_HOSTS`, `MAPS_HTTP_TIMEOUT_SECONDS`, `GEOCODE_CACHE_TTL_SECONDS` |
| Tavily | `TAVILY_ENABLED`, `TAVILY_API_KEY`, `TAVILY_BASE_URL`, `TAVILY_ALLOWED_HOSTS`, `TAVILY_MAX_SEARCHES_PER_TRIP`, `TAVILY_CACHE_TTL_SECONDS`, `TAVILY_NEGATIVE_CACHE_TTL_SECONDS`, `TAVILY_TIMEOUT_SECONDS`, `TAVILY_SNIPPETS_FOR_EXTRACTION`, `ATTRACTION_SNIPPET_MAX_CHARS`, `TAVILY_EXCLUDED_DOMAINS`, `ATTRACTIONS_PER_DESTINATION` |
| Planning rules | `BOOKING_ALLOWED_HOSTS`, `FUEL_COST_PER_KM`, `MAX_DRIVING_HOURS_PER_DAY`, `DRIVING_LATEST_ARRIVAL_HOUR`, `MIN_STAY_HOURS_PER_DESTINATION`, `FOOD_ESTIMATE_PER_DAY_PER_TRAVELER`, `BUDGET_BUFFER_PERCENT` |
| RAG | `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, `RAG_ENABLED`, `EMBEDDING_MODEL`, `EMBEDDING_CACHE_DIR`, `RAG_TOP_K`, `RAG_SCORE_THRESHOLD`, `RAG_TIMEOUT_SECONDS`, `RAG_MODEL_LOAD_TIMEOUT_SECONDS`, `RAG_CACHE_TTL_SECONDS` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_TIMEOUT_SECONDS`, `SMTP_FROM_EMAIL`, `DEV_OTP_EMAIL_FALLBACK_ENABLED` |
| OTP | `OTP_EXPIRY_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN_SECONDS`, `RESET_GRANT_EXPIRY_MINUTES` |
| Login and OTP limits | `LOGIN_RATE_LIMIT_PER_IP`, `LOGIN_RATE_LIMIT_PER_EMAIL`, `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `OTP_REQUEST_RATE_LIMIT_PER_IP`, `OTP_REQUEST_RATE_LIMIT_PER_EMAIL`, `OTP_REQUEST_RATE_LIMIT_WINDOW_SECONDS`, `OTP_VERIFY_RATE_LIMIT_PER_IP`, `OTP_VERIFY_RATE_LIMIT_PER_EMAIL`, `OTP_VERIFY_RATE_LIMIT_WINDOW_SECONDS` |
| Temporary chat | `TEMPORARY_CHAT_TTL_SECONDS`, `TEMPORARY_CHAT_MAX_MESSAGES`, `TEMPORARY_CHAT_MAX_BYTES`, `TEMPORARY_CHAT_RATE_LIMIT_PER_IP`, `TEMPORARY_CHAT_RATE_LIMIT_PER_SESSION`, `TEMPORARY_CHAT_RATE_LIMIT_WINDOW_SECONDS` |
| Planning admission | `PLANNING_RUNS_PER_HOUR`, `PLANNING_RUNS_PER_DAY`, `PLANNING_RUNS_PER_HOUR_GUEST`, `PLANNING_RUNS_PER_TEMP_SESSION`, `PLANNING_MAX_CONCURRENT`, `PLANNING_STREAM_MAX_SECONDS`, `PLANNING_STREAM_TTL_SECONDS`, `PLANNING_STREAM_HEARTBEAT_SECONDS`, `GROQ_DAILY_CALL_BUDGET`, `TAVILY_DAILY_SEARCH_BUDGET` |
| Cleanup | `CLEANUP_ENABLED`, `CLEANUP_INTERVAL_SECONDS`, `CLEANUP_BATCH_SIZE` |
| Tracing | `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` |
| Compose-only | `DEVSAFAR_ENV_FILE`, `API_PORT`, `REDIS_PORT` |
| Tests-only | `TEST_DATABASE_URL`, `TEST_REDIS_URL` |

## Migrations and running the API

Apply migrations before every application start:

```powershell
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

Liveness is `GET /api/v1/health`. Readiness is `GET /api/v1/ready` and checks only
PostgreSQL and Redis.

The root Compose file keeps PostgreSQL and Redis as standalone defaults. The optional
application profile builds the backend, waits for both dependencies to become healthy,
runs Alembic, and then starts Uvicorn on loopback:

```powershell
docker compose -f ..\docker-compose.yml --profile app up --build
```

Set `DEVSAFAR_ENV_FILE` to an uncommitted env-file path when the default local path is not
appropriate. The FastEmbed cache is a named volume. `EMBEDDING_CACHE_DIR` can point to a
different mounted directory.

## Tests and quality checks

Tests require a real PostgreSQL database named exactly `devsafar_test` and a real Redis.
They never load `backend/.env` and never mock authentication, ownership, rate-limit, or
retention enforcement.

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://devsafar:replace-with-local-dev-password@127.0.0.1:5433/devsafar_test'
$env:TEST_REDIS_URL='redis://127.0.0.1:6379/15'
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe app
.venv\Scripts\pytest.exe
```

The autouse fixture removes every application Settings environment variable before each
non-live test and injects only isolated test configuration. A `live` test preserves only
the explicitly supported live integration variables. This cleanup rule prevents developer
shell exports from silently changing ordinary tests.

External-service tests are opt-in:

```powershell
.venv\Scripts\pytest.exe -m live
```

Export only the provider variables needed by the selected live test. Never paste them into
the repository, test output, or issue reports.

## End-to-end smoke test

Start a migrated API and run:

```powershell
.venv\Scripts\python.exe scripts\smoke_e2e.py
.venv\Scripts\python.exe scripts\smoke_e2e.py --base-url http://127.0.0.1:8000
```

The script checks health/readiness, signup/login/profile, saved async SSE, stored trip
retrieval, one sync plan, temporary async SSE, generic forgot-password behavior, logout,
and account cleanup. It prints one `PASS` or `FAIL` per step, exits non-zero on failure,
and never prints passwords, cookies, OTPs, or tokens. No live travel-provider key is
required: stub or degraded `data_sources` are valid structural results.

The smoke account is random and is deleted at the end, including on an earlier failure
when authentication is still available.

## RAG document ingestion

Curated Markdown documents live in `app/rag/documents/`. Each non-example document must
include the provenance front matter enforced by the ingestion code. Validate locally
without embeddings or Qdrant writes:

```powershell
.venv\Scripts\python.exe scripts\ingest_knowledge.py --dry-run
```

After configuring Qdrant, Redis, and the embedding cache, ingest with:

```powershell
.venv\Scripts\python.exe scripts\ingest_knowledge.py
```

RAG content is untrusted context. It cannot override prompts or deterministic date,
budget, route, or booking-link checks, and it must not claim live fares or availability.

## Security model

- Passwords use Argon2id. JWT access tokens contain `sid` and `jti`, are sent only in an
  HttpOnly SameSite=Lax cookie, and are accepted only while the matching database session
  remains active.
- Authenticated writes use double-submit CSRF protection. Logout revokes the active
  session; password change and password reset revoke every session.
- OTP request/resend responses are generic. OTP verifiers and reset grants are keyed
  hashes; attempts, expiry, cooldown, and single use are database-enforced.
- Ownership and expiry are applied in repository queries. Cross-user and expired
  conversations, trips, messages, and streams return 404 rather than revealing existence.
- Temporary chat context is HMAC-bound to a random tab session plus token, stored only in
  Redis with TTL, never persisted in PostgreSQL, and never traced to LangSmith.
- Login, OTP, temporary-chat, saved/guest planning, per-user active-run, and global
  concurrency limits are Redis-backed. Every 429 uses the standard error body and
  `Retry-After`.
- Request bodies and message lengths are bounded. Provider snippets and RAG chunks are
  treated as data. Booking redirects must be HTTPS and match the exact host allowlist.
- API responses use `nosniff`, no-referrer, anti-framing, and no-store headers. CORS uses
  explicit origins with credentials and never allows `*`.
- Structured logging redacts configured secrets, credentials, OTPs, JWTs, cookies, email
  addresses, and connection URLs. User prompts are not logged.

## Retention and cleanup

Saved conversations have `expires_at = created_at + 7 days`; activity never extends it.
Every read rejects expired data immediately. The cleanup loop deletes conversations,
messages, trips, itinerary versions, and matching Redis planning streams in batches and is
idempotent. Temporary chat and planning streams use Redis TTLs.

Account deletion cascades through conversations, messages, trips, and itineraries.
Deletion from the active database does not instantly remove retained backups; production
backup expiry and purge procedures must match the published retention promise.

## Known limitations

- Hotel results are labelled stubs unless an approved provider is configured.
- There are no fabricated live fares, room inventories, seat counts, or confirmed
  bookings; unavailable prices remain unknown.
- Current deterministic feasibility is road-focused. Non-road transport entries are
  comparison/redirect metadata, not verified schedules.
- The public OSRM demo server is testing-only and must not be treated as a production SLA.
- Nominatim use must follow its usage policy, including an identifying user agent, caching,
  low request volume, attribution, and migration to an approved production service when
  traffic grows.
- The LangGraph checkpointer remains deferred; saved results persist in application tables.

## Deployment checklist

- [ ] Terminate HTTPS at a trusted load balancer or reverse proxy; enable secure cookies.
- [ ] Store all secrets in a managed secrets manager; keep env files out of images and Git.
- [ ] Rotate `SECRET_KEY`, database, Redis, SMTP, Groq, Tavily, Qdrant, and LangSmith keys
      through a rehearsed rotation procedure.
- [ ] Put a WAF and rate-aware edge controls in front of the API.
- [ ] Restrict database, Redis, Qdrant, and provider egress networking by least privilege.
- [ ] Run Alembic before application rollout and use health/readiness gates.
- [ ] Configure encrypted PostgreSQL backups, test restores, document backup retention,
      and ensure expiry/purge timing matches the seven-day chat policy and account deletion
      disclosures.
- [ ] Persist and monitor the embedding cache volume; do not bake downloaded models or
      secrets into the image.
- [ ] Alert on readiness failures, authentication abuse, 429 spikes, cleanup failures,
      provider degradation, and planning timeouts without logging sensitive payloads.
