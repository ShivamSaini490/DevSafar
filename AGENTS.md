# DevSafar - Project Rules

## Source of truth
- Specs are in /docs (3 PDFs). Read them before any task.
- Backend folder structure under backend/ is fixed. Do not rename or move folders.
  Create files only for the module being implemented.

## Stack decisions (do not change silently)
- Python 3.12, FastAPI, SQLAlchemy 2 async (asyncpg), Pydantic v2, Alembic
- Auth: JWT access token in HttpOnly cookie + auth_sessions table (revocable). Argon2id hashing.
- LLM: Groq via langchain-groq. Orchestration: LangGraph. Tracing: LangSmith (off by default).
- Vector DB: Qdrant Cloud (qdrant-client) with fastembed embeddings. PostgreSQL 16 for app data. Redis for cache/TTL.
- Background jobs: FastAPI BackgroundTasks first; Celery later only if asked.

## Hard rules
- Never read, print, log or commit real secrets. Never open backend/.env.
  Only .env.example with placeholders goes in the repo.
- Never fabricate live travel data. Prices carry source, fetched_at, price_type
  (live_quote / estimate / unknown). Unknown stays null.
- Saved chat expires_at = created_at + 7 days, never extended. Temporary chat never persists
  and must never send traces to LangSmith.
- Do not weaken security or change the retention policy.
- Dates, budgets, deadlines are computed in Python, not by the LLM.

## Workflow
- One module per task. Before coding, list the files you will change.
- After coding, run tests and report real results. Do not claim tests passed unless you ran them.
- Explain every file in simple Hinglish.
- Stop after the task. Do not start the next module.