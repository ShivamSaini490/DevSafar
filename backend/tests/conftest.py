import os
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command

os.environ["ENVIRONMENT"] = "test"

from app.core.config import Settings  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402


class FakeEmailSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, datetime]] = []

    async def send_password_reset_otp(
        self, *, recipient: str, code: str, expires_at: datetime
    ) -> None:
        self.messages.append((recipient, code, expires_at))

    def latest_code(self, recipient: str) -> str:
        return next(code for email, code, _ in reversed(self.messages) if email == recipient)


def _test_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        raise pytest.UsageError(
            "TEST_DATABASE_URL must be exported and must target the devsafar_test database."
        )
    url = make_url(value)
    if url.database != "devsafar_test":
        raise pytest.UsageError("TEST_DATABASE_URL must target the devsafar_test database.")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        raise pytest.UsageError("TEST_DATABASE_URL must use PostgreSQL with asyncpg.")
    return url.render_as_string(hide_password=False)


def _settings() -> Settings:
    url = make_url(_test_database_url())
    return Settings(
        _env_file=None,
        environment="test",
        debug=False,
        log_level="WARNING",
        secret_key="test-only-secret-key-that-is-long-enough",
        postgres_host=url.host or "127.0.0.1",
        postgres_port=url.port or 5432,
        postgres_db=url.database or "devsafar_test",
        postgres_user=url.username or "devsafar",
        postgres_password=url.password or "",
        redis_url=os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"),
        login_rate_limit_per_ip=20,
        login_rate_limit_per_email=20,
        otp_request_rate_limit_per_ip=20,
        otp_request_rate_limit_per_email=20,
        otp_verify_rate_limit_per_ip=30,
        otp_verify_rate_limit_per_email=30,
        temporary_chat_rate_limit_per_ip=100,
        temporary_chat_rate_limit_per_session=100,
        cleanup_enabled=False,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    settings = _settings()
    os.environ.update(
        {
            "ENVIRONMENT": "test",
            "POSTGRES_HOST": settings.postgres_host,
            "POSTGRES_PORT": str(settings.postgres_port),
            "POSTGRES_DB": settings.postgres_db,
            "POSTGRES_USER": settings.postgres_user,
            "POSTGRES_PASSWORD": settings.postgres_password.get_secret_value(),
        }
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    yield


@pytest.fixture
def settings() -> Settings:
    return _settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    from app.main import create_app

    return create_app(settings)


@pytest_asyncio.fixture(autouse=True)
async def clean_dependencies(settings: Settings) -> AsyncIterator[None]:
    engine = create_db_engine(settings)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))
    from app.db.session import create_redis_client

    redis = create_redis_client(settings)
    await redis.flushdb()
    yield
    await redis.flushdb()
    await redis.aclose()
    await engine.dispose()


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest_asyncio.fixture
async def client(app: FastAPI, fake_email_sender: FakeEmailSender) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="https://testserver") as test_client,
    ):
        app.state.email_sender = fake_email_sender
        yield test_client


@pytest_asyncio.fixture
async def db_session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def valid_signup() -> dict[str, str]:
    return {
        "name": "Dev Safar",
        "email": "traveler@example.com",
        "password": "A-strong-password-42",
        "confirm_password": "A-strong-password-42",
    }
