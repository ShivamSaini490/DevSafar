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
| Redis | `REDIS_URL`, `REDIS_SOCKET_TIMEOUT_SECONDS` |
| Groq and graph | `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_EXTRACTION_MODEL`, `GROQ_EXTRACTION_FALLBACK_MODEL`, `GROQ_EXTRACTION_MAX_COMPLETION_TOKENS`, `GROQ_EXTRACTION_RETRY_MAX_COMPLETION_TOKENS`, `GROQ_EXTRACTION_REASONING_EFFORT`, `GROQ_EXTRACTION_INCLUDE_REASONING`, `GROQ_TIMEOUT_SECONDS`, `GROQ_MAX_RETRY_WAIT_SECONDS`, `GRAPH_TIMEOUT_SECONDS` |
| Maps | `MAPS_PROVIDER`, `OSRM_BASE_URL`, `NOMINATIM_BASE_URL`, `NOMINATIM_USER_AGENT`, `NOMINATIM_COUNTRY_CODE`, `MAPS_ALLOWED_HOSTS`, `MAPS_HTTP_TIMEOUT_SECONDS`, `GEOCODE_CACHE_TTL_SECONDS` |
| Tavily | `TAVILY_ENABLED`, `TAVILY_API_KEY`, `TAVILY_BASE_URL`, `TAVILY_ALLOWED_HOSTS`, `TAVILY_MAX_SEARCHES_PER_TRIP`, `TAVILY_CACHE_TTL_SECONDS`, `TAVILY_NEGATIVE_CACHE_TTL_SECONDS`, `TAVILY_TIMEOUT_SECONDS`, `TAVILY_SNIPPETS_FOR_EXTRACTION`, `ATTRACTION_SNIPPET_MAX_CHARS`, `TAVILY_EXCLUDED_DOMAINS`, `ATTRACTIONS_PER_DESTINATION` |
| Planning rules | `BOOKING_ALLOWED_HOSTS`, `FUEL_COST_PER_KM`, `MAX_DRIVING_HOURS_PER_DAY`, `DRIVING_LATEST_ARRIVAL_HOUR`, `MIN_STAY_HOURS_PER_DESTINATION`, `FOOD_ESTIMATE_PER_DAY_PER_TRAVELER`, `BUDGET_BUFFER_PERCENT` |
| Estimate inputs | `ESTIMATE_TRAIN_*_INR_PER_KM`, `ESTIMATE_BUS_*_INR_PER_KM`, `ESTIMATE_FLIGHT_*_INR`, `ESTIMATE_*_SPEED_*_KMPH`, `ESTIMATE_*_OVERHEAD_*_HOURS`, `ESTIMATE_TRAIN_DISTANCE_THRESHOLD_KM`, `ESTIMATE_HOTEL_*_INR`, `ESTIMATE_FOOD_*_PER_DAY_PER_TRAVELER`, `ESTIMATE_LOCAL_TRANSPORT_*_PER_DAY_PER_TRAVELER` |
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

Planning SSE reads use a dedicated Redis connection. Its socket timeout is always larger
than the bounded `XREAD BLOCK` interval, while ordinary Redis commands use
`REDIS_SOCKET_TIMEOUT_SECONDS`. A Redis read timeout becomes a heartbeat; bounded
connection failures produce a safe terminal SSE failure instead of escaping the response.

Attraction extraction uses `max_completion_tokens`, because reasoning tokens count toward
the generated completion budget. GPT-OSS extraction defaults to low reasoning effort and
excludes reasoning text. An empty `finish_reason=length` result gets one larger-budget
retry; all attempts still share the three-call per-city cap and Redis-backed Groq budget.

## How estimates work and what they are not

The estimate engine is deterministic Python and makes no external calls. Road distance
comes from the configured maps result; flight geometry uses the two already-geocoded city
points. Decimal arithmetic applies configurable rate ranges for road, train, bus, flight,
hotel tiers, food, and local transport. Every generated price is labelled `estimate`, has
a source and timestamp, and carries the note `rates are configurable estimates`.

These numbers are **not fares, timetables, availability, or booking quotes**. A missing
road distance stays unknown. A flight stays unknown when either city is absent from the
reviewable airport mapping. Non-road feasibility stays unverified until an actual
timetable provider is added. No estimate is ever promoted to `live_quote`.

**PLACEHOLDER - owner must verify every default below against official sources before
production use.** The detailed verification checklist is
[`ESTIMATE_RATES_TO_VERIFY.md`](../docs/ESTIMATE_RATES_TO_VERIFY.md).

| Config keys | Placeholder defaults | Meaning |
|---|---:|---|
| `FUEL_COST_PER_KM` | 12.00 | Private-road cost per kilometre |
| `ESTIMATE_TRAIN_SLEEPER_INR_PER_KM`, `ESTIMATE_TRAIN_3AC_INR_PER_KM`, `ESTIMATE_TRAIN_2AC_INR_PER_KM` | 0.75 / 1.50 / 2.25 | Train class range |
| `ESTIMATE_BUS_ORDINARY_INR_PER_KM`, `ESTIMATE_BUS_AC_INR_PER_KM`, `ESTIMATE_BUS_SLEEPER_INR_PER_KM` | 1.20 / 2.00 / 2.50 | Bus type range |
| `ESTIMATE_FLIGHT_BASE_MIN_INR`, `ESTIMATE_FLIGHT_BASE_MAX_INR` | 2500 / 4500 | Flight base range |
| `ESTIMATE_FLIGHT_PER_KM_MIN_INR`, `ESTIMATE_FLIGHT_PER_KM_MAX_INR` | 3.00 / 7.00 | Flight distance rate range |
| `ESTIMATE_FLIGHT_MIN_FARE_MIN_INR`, `ESTIMATE_FLIGHT_MIN_FARE_MAX_INR` | 3000 / 5000 | Flight minimum range |
| `ESTIMATE_ROAD_SPEED_MIN_KMPH`, `ESTIMATE_ROAD_SPEED_MAX_KMPH` | 40 / 65 | Road formula speed range |
| `ESTIMATE_TRAIN_SPEED_MIN_KMPH`, `ESTIMATE_TRAIN_SPEED_MAX_KMPH` | 45 / 70 | Train formula speed range |
| `ESTIMATE_BUS_SPEED_MIN_KMPH`, `ESTIMATE_BUS_SPEED_MAX_KMPH` | 35 / 55 | Bus formula speed range |
| `ESTIMATE_FLIGHT_SPEED_MIN_KMPH`, `ESTIMATE_FLIGHT_SPEED_MAX_KMPH` | 650 / 800 | Flight formula speed range |
| `ESTIMATE_TRAIN_OVERHEAD_MIN_HOURS`, `ESTIMATE_TRAIN_OVERHEAD_MAX_HOURS` | 1 / 2 | Station overhead range |
| `ESTIMATE_BUS_OVERHEAD_MIN_HOURS`, `ESTIMATE_BUS_OVERHEAD_MAX_HOURS` | 0.5 / 1 | Bus overhead range |
| `ESTIMATE_FLIGHT_OVERHEAD_MIN_HOURS`, `ESTIMATE_FLIGHT_OVERHEAD_MAX_HOURS` | 3 / 5 | Airport overhead range |
| `ESTIMATE_TRAIN_DISTANCE_THRESHOLD_KM` | 100 | Adds station-availability caution below this distance |
| `ESTIMATE_HOTEL_BUDGET_MIN_INR`, `ESTIMATE_HOTEL_BUDGET_MAX_INR` | 1000 / 1800 | Budget tier per night |
| `ESTIMATE_HOTEL_STANDARD_MIN_INR`, `ESTIMATE_HOTEL_STANDARD_MAX_INR` | 2000 / 3500 | Standard tier per night |
| `ESTIMATE_HOTEL_COMFORT_MIN_INR`, `ESTIMATE_HOTEL_COMFORT_MAX_INR` | 4000 / 6500 | Comfort tier per night |
| `ESTIMATE_FOOD_MIN_PER_DAY_PER_TRAVELER`, `ESTIMATE_FOOD_MAX_PER_DAY_PER_TRAVELER` | 400 / 800 | Food per day per traveller |
| `ESTIMATE_LOCAL_TRANSPORT_MIN_PER_DAY_PER_TRAVELER`, `ESTIMATE_LOCAL_TRANSPORT_MAX_PER_DAY_PER_TRAVELER` | 250 / 600 | Local transport per day per traveller |

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

## Price sources, statuses and fallback

Flight and hotel prices follow one deterministic chain:

1. Reuse the short-lived Redis result for the exact same query.
2. If enabled and within both SerpApi counters, request a current Google Flights or
   Google Hotels search result through SerpApi.
3. After provider failure, use one or two comparable rows as `previous`, or three or more
   rows as an `estimated` median with observed min/max and sample count.
4. If history is unusable, use the deterministic `formula_estimate` range.
5. If the provider successfully returns no matching result, return `unavailable` and stop;
   do not substitute history or a formula.

`live_search_result` means only that the provider returned a numeric search result now. It
is never a booking claim, every quote is `bookable=false`, and the response states that it
is a search result rather than a confirmed booking. Unknown amounts remain `null`, never
zero. Budget totals include only numeric components and list unavailable components in
`omitted_categories`.

| Key | Default | Purpose |
|---|---:|---|
| `GOOGLE_SERP_API_KEY` | empty | Owner-supplied SerpApi secret; never commit it. |
| `SERPAPI_ENABLED` | `false` | Enables current flight/hotel searches when a key exists. |
| `SERPAPI_MONTHLY_BUDGET` | `250` | Shared Redis-backed monthly flight + hotel call cap. |
| `SERPAPI_MAX_SEARCHES_PER_TRIP` | `3` | Per-trip call cap after cache lookup. |
| `FLIGHT_CACHE_TTL_SECONDS` | `900` | Exact-query flight cache TTL. |
| `HOTEL_CACHE_TTL_SECONDS` | `1800` | Exact-query hotel cache TTL. |
| `PRICE_HISTORY_ENABLED` | `true` | Enables storage of successful live provider quotes. |
| `PRICE_HISTORY_MAX_AGE_DAYS` | `90` | Maximum observation age for fallback comparison. |
| `PRICE_HISTORY_RETENTION_DAYS` | `180` | Cleanup retention for anonymized price rows. |
| `ALLOW_DEMO_PRICE_DATA` | `false` | Allows explicitly demo-tagged rows in fallback. |

Price history stores no prompt, user ID, conversation ID, or trip ID. Provider terms for
caching and storing search results must be checked and approved by the owner before live
use. Set `PRICE_HISTORY_ENABLED=false` to disable storing new provider results.

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
