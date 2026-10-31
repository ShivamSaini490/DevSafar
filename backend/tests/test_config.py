import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_tavily_defaults_are_disabled_and_bounded() -> None:
    settings = Settings(_env_file=None, environment="test", secret_key="test-secret")

    assert settings.tavily_enabled is False
    assert settings.tavily_max_searches_per_trip == 2
    assert settings.tavily_cache_ttl_seconds == 604_800
    assert settings.tavily_timeout_seconds == 10
    assert settings.attractions_per_destination == 6
    assert settings.tavily_excluded_domain_set == {
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "x.com",
        "pinterest.com",
    }


@pytest.mark.parametrize(
    "base_url",
    ["http://api.tavily.com", "https://not-tavily.example"],
)
def test_tavily_base_url_requires_https_and_allowlisted_host(base_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="test",
            secret_key="test-secret",
            tavily_base_url=base_url,
        )


def test_enabled_tavily_without_key_has_clear_startup_warning() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="test-secret",
        tavily_enabled=True,
        tavily_api_key=None,
    )

    assert settings.tavily_configuration_warnings() == (
        "TAVILY_ENABLED is true but TAVILY_API_KEY is empty; "
        "attractions will use the labelled stub fallback.",
    )


def test_tavily_without_groq_has_grounding_warning() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="test-secret",
        tavily_enabled=True,
        tavily_api_key="placeholder-tavily-key",
        groq_api_key=None,
    )

    assert settings.tavily_configuration_warnings() == (
        "Tavily is configured but GROQ_API_KEY is empty; grounded attraction "
        "extraction will use the labelled stub fallback.",
    )
