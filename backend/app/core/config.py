"""Application settings, loaded from environment variables (or a .env file).

Production refuses to start with insecure defaults.
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-insecure-secret-change-me-0000000000000000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Frontdesk AI"
    environment: str = "development"  # development | test | production

    # --- secrets -----------------------------------------------------------
    secret_key: str = _DEV_SECRET
    encryption_key: str = ""  # 32-byte url-safe base64 (AES-256-GCM at rest)

    # --- infrastructure ----------------------------------------------------
    database_url: str = "sqlite:///./dev.db"
    redis_url: str | None = None
    auto_create_tables: bool = True
    frontend_url: str = "http://localhost:5173"  # dashboard + widget host (public URL)
    cors_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = ["*"]
    max_request_bytes: int = 1_000_000
    global_rate_limit_per_minute: int = 600

    # --- auth ----------------------------------------------------------------
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    jwt_issuer: str = "frontdesk-ai"
    jwt_audience: str = "frontdesk-ai-web"
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    password_reset_ttl_minutes: int = 30
    invitation_ttl_days: int = 7
    # Comma-separated emails that get platform-admin rights when they register / log in.
    platform_admin_emails: str = ""

    # --- AI ------------------------------------------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    ai_timeout_seconds: float = 30.0

    # --- widget abuse limits ---------------------------------------------
    widget_messages_per_minute: int = 12          # per visitor IP
    widget_conversations_per_hour: int = 20        # per visitor IP
    max_messages_per_conversation: int = 60

    # --- billing (Stripe) ---------------------------------------------------
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_starter: str | None = None
    stripe_price_growth: str | None = None
    stripe_price_pro: str | None = None
    trial_days: int = 14

    # --- outbound mail -------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@example.com"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip()}

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.is_production:
            problems = []
            if self.secret_key == _DEV_SECRET or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be a random value of at least 32 characters")
            if not self.encryption_key:
                problems.append("ENCRYPTION_KEY is required")
            if "*" in self.allowed_hosts:
                problems.append("ALLOWED_HOSTS must list your real hostnames")
            if self.database_url.startswith("sqlite"):
                problems.append("Use PostgreSQL in production")
            if not self.frontend_url.startswith("https://"):
                problems.append("FRONTEND_URL must be https in production")
            if self.stripe_secret_key and not self.stripe_webhook_secret:
                problems.append("STRIPE_WEBHOOK_SECRET is required when Stripe is enabled")
            if problems:
                raise ValueError("Insecure production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
