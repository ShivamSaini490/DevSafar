# DevSafar Backend - Foundation

Python 3.12 FastAPI foundation with async PostgreSQL, Redis, versioned health routes,
safe error responses, structured redacted logs, Docker, and tests.

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

4. Verify:

   ```text
   GET http://127.0.0.1:8000/api/v1/health
   GET http://127.0.0.1:8000/api/v1/ready
   ```

`/health` proves the API process is alive. `/ready` returns ready only when PostgreSQL
and Redis respond successfully. Groq, Qdrant, SMTP, and LangSmith are intentionally not
part of readiness.

## Quality checks

```powershell
ruff check .
pytest
```

## Tracing and sensitive data

LangSmith tracing defaults to off. It must remain off for every temporary-chat execution.
Before any saved-chat trace is sent, passwords, OTPs, tokens, cookies, email addresses,
API keys, and other sensitive fields must be redacted. Application logs use the same
redaction rule and must never contain raw secrets.
