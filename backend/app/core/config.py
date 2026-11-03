import os
import secrets
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.utils.url_validator import parse_host_allowlist, validate_external_base_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an explicit env file.

    Environment variables take precedence over values in the env file. Callers can
    pass ``_env_file=None`` when dotenv loading must be disabled, such as in tests.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_prefix="",
    )

    _uses_ephemeral_auth_secret: bool = PrivateAttr(default=False)

    app_name: str = "DevSafar API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: SecretStr | None = None
    access_token_minutes: int = Field(default=60, ge=5, le=1440)
    access_token_cookie_name: str = "access_token"
    csrf_cookie_name: str = "csrf_token"
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    max_request_body_bytes: int = Field(default=1_048_576, ge=8192, le=10_485_760)

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "devsafar"
    postgres_user: str = "devsafar"
    postgres_password: SecretStr = SecretStr("replace-with-local-dev-password")

    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    redis_socket_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_extraction_model: str = ""
    groq_extraction_fallback_model: str = ""
    groq_extraction_max_completion_tokens: int = Field(default=4096, ge=256, le=65_536)
    groq_extraction_retry_max_completion_tokens: int = Field(
        default=8192,
        ge=512,
        le=65_536,
    )
    groq_extraction_reasoning_effort: Literal["low", "medium", "high"] = "low"
    groq_extraction_include_reasoning: bool = False
    groq_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    groq_max_retry_wait_seconds: float = Field(default=8.0, ge=0, le=60)
    graph_timeout_seconds: float = Field(default=60.0, gt=0, le=180)
    maps_provider: Literal["stub", "osm"] = "stub"
    osrm_base_url: str = "https://router.project-osrm.org"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = Field(
        default="DevSafar/0.1 road-routing-backend",
        min_length=10,
        max_length=200,
    )
    nominatim_country_code: str = Field(default="in", pattern=r"^[a-zA-Z]{2}$")
    maps_allowed_hosts: str = "router.project-osrm.org,nominatim.openstreetmap.org"
    maps_http_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    geocode_cache_ttl_seconds: int = Field(default=2_592_000, ge=86_400)
    google_serp_api_key: SecretStr | None = None
    serpapi_enabled: bool = False
    serpapi_base_url: str = "https://serpapi.com/search.json"
    serpapi_allowed_hosts: str = "serpapi.com,www.serpapi.com"
    serpapi_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    serpapi_max_retries: int = Field(default=2, ge=0, le=2)
    serpapi_max_retry_wait_seconds: float = Field(default=5.0, ge=0, le=30)
    serpapi_auth_circuit_minutes: int = Field(default=10, ge=1, le=120)
    serpapi_monthly_budget: int = Field(default=250, ge=0)
    serpapi_max_searches_per_trip: int = Field(default=3, ge=0, le=20)
    flight_cache_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    hotel_cache_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    price_history_enabled: bool = True
    price_history_max_age_days: int = Field(default=90, ge=1, le=3650)
    price_history_retention_days: int = Field(default=180, ge=1, le=3650)
    allow_demo_price_data: bool = False
    tavily_enabled: bool = False
    tavily_api_key: SecretStr | None = None
    tavily_base_url: str = "https://api.tavily.com"
    tavily_allowed_hosts: str = "api.tavily.com"
    tavily_max_searches_per_trip: int = Field(default=2, ge=0, le=10)
    tavily_cache_ttl_seconds: int = Field(default=604_800, ge=60)
    tavily_negative_cache_ttl_seconds: int = Field(default=120, ge=1, le=3600)
    tavily_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    tavily_snippets_for_extraction: int = Field(default=4, ge=1, le=10)
    attraction_snippet_max_chars: int = Field(default=700, ge=100, le=5000)
    tavily_excluded_domains: str = (
        "youtube.com,youtu.be,facebook.com,instagram.com,tiktok.com,x.com,pinterest.com"
    )
    attractions_per_destination: int = Field(default=6, ge=1, le=12)
    booking_allowed_hosts: str = (
        "www.irctc.co.in,www.makemytrip.com,www.redbus.in,www.google.com,www.booking.com"
    )
    fuel_cost_per_km: Decimal = Field(default=Decimal("12.00"), gt=0)
    estimate_train_sleeper_inr_per_km: Decimal = Field(default=Decimal("0.75"), gt=0)
    estimate_train_3ac_inr_per_km: Decimal = Field(default=Decimal("1.50"), gt=0)
    estimate_train_2ac_inr_per_km: Decimal = Field(default=Decimal("2.25"), gt=0)
    estimate_bus_ordinary_inr_per_km: Decimal = Field(default=Decimal("1.20"), gt=0)
    estimate_bus_ac_inr_per_km: Decimal = Field(default=Decimal("2.00"), gt=0)
    estimate_bus_sleeper_inr_per_km: Decimal = Field(default=Decimal("2.50"), gt=0)
    estimate_flight_base_min_inr: Decimal = Field(default=Decimal("2500"), gt=0)
    estimate_flight_base_max_inr: Decimal = Field(default=Decimal("4500"), gt=0)
    estimate_flight_per_km_min_inr: Decimal = Field(default=Decimal("3.00"), gt=0)
    estimate_flight_per_km_max_inr: Decimal = Field(default=Decimal("7.00"), gt=0)
    estimate_flight_min_fare_min_inr: Decimal = Field(default=Decimal("3000"), gt=0)
    estimate_flight_min_fare_max_inr: Decimal = Field(default=Decimal("5000"), gt=0)
    estimate_road_speed_min_kmph: Decimal = Field(default=Decimal("40"), gt=0)
    estimate_road_speed_max_kmph: Decimal = Field(default=Decimal("65"), gt=0)
    estimate_train_speed_min_kmph: Decimal = Field(default=Decimal("45"), gt=0)
    estimate_train_speed_max_kmph: Decimal = Field(default=Decimal("70"), gt=0)
    estimate_bus_speed_min_kmph: Decimal = Field(default=Decimal("35"), gt=0)
    estimate_bus_speed_max_kmph: Decimal = Field(default=Decimal("55"), gt=0)
    estimate_flight_speed_min_kmph: Decimal = Field(default=Decimal("650"), gt=0)
    estimate_flight_speed_max_kmph: Decimal = Field(default=Decimal("800"), gt=0)
    estimate_train_overhead_min_hours: Decimal = Field(default=Decimal("1"), ge=0)
    estimate_train_overhead_max_hours: Decimal = Field(default=Decimal("2"), ge=0)
    estimate_bus_overhead_min_hours: Decimal = Field(default=Decimal("0.5"), ge=0)
    estimate_bus_overhead_max_hours: Decimal = Field(default=Decimal("1"), ge=0)
    estimate_flight_overhead_min_hours: Decimal = Field(default=Decimal("3"), ge=0)
    estimate_flight_overhead_max_hours: Decimal = Field(default=Decimal("5"), ge=0)
    estimate_train_distance_threshold_km: Decimal = Field(default=Decimal("100"), ge=0)
    estimate_hotel_budget_min_inr: Decimal = Field(default=Decimal("1000"), gt=0)
    estimate_hotel_budget_max_inr: Decimal = Field(default=Decimal("1800"), gt=0)
    estimate_hotel_standard_min_inr: Decimal = Field(default=Decimal("2000"), gt=0)
    estimate_hotel_standard_max_inr: Decimal = Field(default=Decimal("3500"), gt=0)
    estimate_hotel_comfort_min_inr: Decimal = Field(default=Decimal("4000"), gt=0)
    estimate_hotel_comfort_max_inr: Decimal = Field(default=Decimal("6500"), gt=0)
    estimate_food_min_per_day_per_traveler: Decimal = Field(default=Decimal("400"), ge=0)
    estimate_food_max_per_day_per_traveler: Decimal = Field(default=Decimal("800"), ge=0)
    estimate_local_transport_min_per_day_per_traveler: Decimal = Field(
        default=Decimal("250"), ge=0
    )
    estimate_local_transport_max_per_day_per_traveler: Decimal = Field(
        default=Decimal("600"), ge=0
    )
    max_driving_hours_per_day: int = Field(default=10, ge=1, le=16)
    driving_latest_arrival_hour: int = Field(default=21, ge=7, le=23)
    min_stay_hours_per_destination: int = Field(default=6, ge=1, le=48)
    food_estimate_per_day_per_traveler: Decimal | None = Field(
        default=None,
        ge=0,
        description="Optional INR food estimate per trip day per traveler.",
    )
    budget_buffer_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Optional buffer percentage applied to the known subtotal.",
    )
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = Field(
        default="devsafar_travel_knowledge",
        pattern=r"^[A-Za-z0-9_-]{1,100}$",
    )
    rag_enabled: bool = False
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        min_length=1,
        max_length=200,
    )
    embedding_cache_dir: str | None = None
    rag_top_k: int = Field(default=3, ge=1, le=10)
    rag_score_threshold: float = Field(default=0.45, ge=0, le=1)
    rag_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    rag_model_load_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    rag_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)

    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    smtp_from_email: str | None = None
    dev_otp_email_fallback_enabled: bool = False

    otp_expiry_minutes: int = Field(default=5, ge=1, le=30)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=30, le=3600)
    reset_grant_expiry_minutes: int = Field(default=10, ge=1, le=30)

    login_rate_limit_per_ip: int = Field(default=10, ge=1)
    login_rate_limit_per_email: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1)
    otp_request_rate_limit_per_ip: int = Field(default=10, ge=1)
    otp_request_rate_limit_per_email: int = Field(default=5, ge=1)
    otp_request_rate_limit_window_seconds: int = Field(default=300, ge=1)
    otp_verify_rate_limit_per_ip: int = Field(default=20, ge=1)
    otp_verify_rate_limit_per_email: int = Field(default=10, ge=1)
    otp_verify_rate_limit_window_seconds: int = Field(default=300, ge=1)

    temporary_chat_ttl_seconds: int = Field(default=1800, ge=1, le=86400)
    temporary_chat_max_messages: int = Field(default=20, ge=2, le=100)
    temporary_chat_max_bytes: int = Field(default=65536, ge=8192, le=262144)
    temporary_chat_rate_limit_per_ip: int = Field(default=30, ge=1)
    temporary_chat_rate_limit_per_session: int = Field(default=20, ge=1)
    temporary_chat_rate_limit_window_seconds: int = Field(default=60, ge=1)

    planning_runs_per_hour: int = Field(default=10, ge=1)
    planning_runs_per_day: int = Field(default=40, ge=1)
    planning_runs_per_hour_guest: int = Field(default=5, ge=1)
    planning_runs_per_temp_session: int = Field(default=10, ge=1)
    planning_max_concurrent: int = Field(default=3, ge=1, le=100)
    planning_stream_max_seconds: int = Field(default=120, ge=1, le=600)
    planning_stream_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    planning_stream_heartbeat_seconds: int = Field(default=15, ge=1, le=60)
    groq_daily_call_budget: int = Field(default=1000, ge=0)
    tavily_daily_search_budget: int = Field(default=200, ge=0)

    cleanup_enabled: bool = True
    cleanup_interval_seconds: int = Field(default=900, ge=1)
    cleanup_batch_size: int = Field(default=100, ge=1, le=1000)

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "devsafar"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @field_validator("qdrant_url")
    @classmethod
    def validate_qdrant_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if not hostname:
            raise ValueError("QDRANT_URL must contain a hostname")
        return validate_external_base_url(
            value,
            allowed_hosts=frozenset({hostname}),
        )

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_allowed_origins(cls, value: str) -> str:
        origins = tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())
        if not origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS_ALLOWED_ORIGINS must contain exact HTTP(S) origins")
        return ",".join(dict.fromkeys(origins))

    @field_validator("embedding_cache_dir")
    @classmethod
    def normalize_embedding_cache_dir(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        secret_is_missing = (
            self.secret_key is None or not self.secret_key.get_secret_value().strip()
        )
        if self.environment in {"staging", "production"} and secret_is_missing:
            raise ValueError("SECRET_KEY must be configured outside development")
        if self.environment == "development" and secret_is_missing:
            self.secret_key = SecretStr(secrets.token_urlsafe(48))
            self._uses_ephemeral_auth_secret = True
        if self.environment != "development" and self.dev_otp_email_fallback_enabled:
            raise ValueError("DEV_OTP_EMAIL_FALLBACK_ENABLED is development-only")
        allowed_hosts = parse_host_allowlist(self.maps_allowed_hosts)
        self.osrm_base_url = validate_external_base_url(
            self.osrm_base_url,
            allowed_hosts=allowed_hosts,
        )
        self.nominatim_base_url = validate_external_base_url(
            self.nominatim_base_url,
            allowed_hosts=allowed_hosts,
        )
        tavily_allowed_hosts = parse_host_allowlist(self.tavily_allowed_hosts)
        parse_host_allowlist(self.tavily_excluded_domains)
        self.tavily_base_url = validate_external_base_url(
            self.tavily_base_url,
            allowed_hosts=tavily_allowed_hosts,
        )
        serpapi_allowed_hosts = parse_host_allowlist(self.serpapi_allowed_hosts)
        self.serpapi_base_url = validate_external_base_url(
            self.serpapi_base_url,
            allowed_hosts=serpapi_allowed_hosts,
        )
        if self.price_history_retention_days < self.price_history_max_age_days:
            raise ValueError(
                "PRICE_HISTORY_RETENTION_DAYS must be >= PRICE_HISTORY_MAX_AGE_DAYS"
            )
        parse_host_allowlist(self.booking_allowed_hosts)
        if (
            self.groq_extraction_retry_max_completion_tokens
            <= self.groq_extraction_max_completion_tokens
        ):
            raise ValueError(
                "GROQ_EXTRACTION_RETRY_MAX_COMPLETION_TOKENS must be greater than "
                "GROQ_EXTRACTION_MAX_COMPLETION_TOKENS"
            )
        estimate_ranges = (
            ("flight base fare", self.estimate_flight_base_min_inr, self.estimate_flight_base_max_inr),
            ("flight per-km rate", self.estimate_flight_per_km_min_inr, self.estimate_flight_per_km_max_inr),
            ("flight minimum fare", self.estimate_flight_min_fare_min_inr, self.estimate_flight_min_fare_max_inr),
            ("road speed", self.estimate_road_speed_min_kmph, self.estimate_road_speed_max_kmph),
            ("train speed", self.estimate_train_speed_min_kmph, self.estimate_train_speed_max_kmph),
            ("bus speed", self.estimate_bus_speed_min_kmph, self.estimate_bus_speed_max_kmph),
            ("flight speed", self.estimate_flight_speed_min_kmph, self.estimate_flight_speed_max_kmph),
            ("train overhead", self.estimate_train_overhead_min_hours, self.estimate_train_overhead_max_hours),
            ("bus overhead", self.estimate_bus_overhead_min_hours, self.estimate_bus_overhead_max_hours),
            ("flight overhead", self.estimate_flight_overhead_min_hours, self.estimate_flight_overhead_max_hours),
            ("budget hotel", self.estimate_hotel_budget_min_inr, self.estimate_hotel_budget_max_inr),
            ("standard hotel", self.estimate_hotel_standard_min_inr, self.estimate_hotel_standard_max_inr),
            ("comfort hotel", self.estimate_hotel_comfort_min_inr, self.estimate_hotel_comfort_max_inr),
            ("food", self.estimate_food_min_per_day_per_traveler, self.estimate_food_max_per_day_per_traveler),
            ("local transport", self.estimate_local_transport_min_per_day_per_traveler, self.estimate_local_transport_max_per_day_per_traveler),
        )
        for label, minimum, maximum in estimate_ranges:
            if minimum > maximum:
                raise ValueError(f"Estimate {label} minimum cannot exceed maximum")
        return self

    @property
    def maps_host_allowlist(self) -> frozenset[str]:
        return parse_host_allowlist(self.maps_allowed_hosts)

    @property
    def tavily_host_allowlist(self) -> frozenset[str]:
        return parse_host_allowlist(self.tavily_allowed_hosts)

    @property
    def tavily_excluded_domain_set(self) -> frozenset[str]:
        return parse_host_allowlist(self.tavily_excluded_domains)

    @property
    def serpapi_host_allowlist(self) -> frozenset[str]:
        return parse_host_allowlist(self.serpapi_allowed_hosts)

    @property
    def booking_host_allowlist(self) -> frozenset[str]:
        return parse_host_allowlist(self.booking_allowed_hosts)

    @property
    def cors_origin_list(self) -> list[str]:
        return self.cors_allowed_origins.split(",")

    @property
    def tavily_configured(self) -> bool:
        return bool(
            self.tavily_enabled
            and self.tavily_api_key is not None
            and self.tavily_api_key.get_secret_value().strip()
        )

    @property
    def serpapi_configured(self) -> bool:
        return bool(
            self.serpapi_enabled
            and self.google_serp_api_key is not None
            and self.google_serp_api_key.get_secret_value().strip()
        )

    def serpapi_configuration_warnings(self) -> tuple[str, ...]:
        if self.serpapi_enabled and not self.serpapi_configured:
            return (
                "SERPAPI_ENABLED is true but GOOGLE_SERP_API_KEY is empty; "
                "prices will use history or formula fallback.",
            )
        return ()

    def tavily_configuration_warnings(self) -> tuple[str, ...]:
        if self.tavily_enabled and not self.tavily_configured:
            return (
                "TAVILY_ENABLED is true but TAVILY_API_KEY is empty; "
                "attractions will use the labelled stub fallback.",
            )
        if self.tavily_configured and not self.groq_configured:
            return (
                "Tavily is configured but GROQ_API_KEY is empty; grounded attraction "
                "extraction will use the labelled stub fallback.",
            )
        return ()

    @property
    def rag_configured(self) -> bool:
        return bool(
            self.rag_enabled
            and self.qdrant_url
            and self.qdrant_api_key is not None
            and self.qdrant_api_key.get_secret_value().strip()
        )

    def rag_configuration_warnings(self) -> tuple[str, ...]:
        if self.rag_enabled and not self.rag_configured:
            return (
                "RAG_ENABLED is true but QDRANT_URL or QDRANT_API_KEY is empty; "
                "destination knowledge will degrade safely.",
            )
        return ()

    @property
    def database_url(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def redis_connection_url(self) -> str:
        return self.redis_url.get_secret_value()

    @property
    def secure_auth_cookies(self) -> bool:
        return self.environment != "development"

    @property
    def auth_secret(self) -> str:
        if self.secret_key is None:
            raise ValueError("SECRET_KEY is required for authentication operations")
        return self.secret_key.get_secret_value()

    @property
    def uses_ephemeral_auth_secret(self) -> bool:
        return self._uses_ephemeral_auth_secret

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key is not None and self.groq_api_key.get_secret_value().strip())

    @property
    def groq_extraction_model_name(self) -> str:
        return self.groq_extraction_model_chain[0]

    @property
    def groq_extraction_fallback_model_name(self) -> str:
        chain = self.groq_extraction_model_chain
        return chain[1] if len(chain) > 1 else chain[0]

    @property
    def groq_extraction_model_chain(self) -> tuple[str, ...]:
        candidates = (
            self.groq_extraction_model.strip(),
            self.groq_extraction_fallback_model.strip(),
            self.groq_model.strip(),
        )
        return tuple(dict.fromkeys(model for model in candidates if model))

    @property
    def smtp_use_implicit_tls(self) -> bool:
        if self.smtp_port == 465:
            return True
        if self.smtp_port == 587:
            return False
        return self.smtp_use_tls

    @property
    def smtp_start_tls(self) -> bool:
        if self.smtp_port == 465:
            return False
        if self.smtp_port == 587:
            return True
        return not self.smtp_use_tls

    def smtp_configuration_warnings(self) -> tuple[str, ...]:
        if not self.smtp_host:
            return ()
        warnings: list[str] = []
        if self.smtp_port == 587 and self.smtp_use_tls:
            warnings.append(
                "SMTP port 587 requires STARTTLS; SMTP_USE_TLS should be false. "
                "DevSafar will use STARTTLS for this standard port."
            )
        if self.smtp_port == 465 and not self.smtp_use_tls:
            warnings.append(
                "SMTP port 465 requires implicit TLS; SMTP_USE_TLS should be true. "
                "DevSafar will use implicit TLS for this standard port."
            )
        username_missing = not self.smtp_username or not self.smtp_username.strip()
        password_missing = (
            self.smtp_password is None or not self.smtp_password.get_secret_value().strip()
        )
        if username_missing or password_missing:
            warnings.append(
                "SMTP_HOST is configured but SMTP_USERNAME or SMTP_PASSWORD is empty; "
                "OTP email delivery will fail safely in the background."
            )
        return tuple(warnings)

    def redaction_secret_values(self) -> tuple[str, ...]:
        optional_secrets = (
            self.secret_key,
            self.groq_api_key,
            self.google_serp_api_key,
            self.tavily_api_key,
            self.qdrant_api_key,
            self.smtp_password,
            self.langsmith_api_key,
        )
        values = [
            self.postgres_password.get_secret_value(),
            self.redis_url.get_secret_value(),
        ]
        values.extend(
            secret.get_secret_value() for secret in optional_secrets if secret is not None
        )
        return tuple(value for value in values if value)


@lru_cache
def get_settings() -> Settings:
    env_file: Path | None = (
        None if os.getenv("ENVIRONMENT", "").lower() == "test" else DEFAULT_ENV_FILE
    )
    # pydantic-settings supports these runtime init keywords, but its mypy-generated
    # Settings signature does not expose them.
    return Settings(  # type: ignore[call-arg]
        _env_file=env_file,
        _env_file_encoding="utf-8",
    )
