"""Runtime configuration, read from environment variables."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/complanning")
    # Railway and Heroku style URLs work directly with libpq; normalise the scheme.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    # Cookies are marked Secure unless explicitly disabled for local development.
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", True))
    # Absolute session lifetime; the inactivity timeout comes from tenant security policy.
    session_max_hours: int = field(default_factory=lambda: int(os.environ.get("SESSION_MAX_HOURS", "12")))
    db_pool_size: int = field(default_factory=lambda: int(os.environ.get("DB_POOL_SIZE", "10")))
    platform_admin_email: str | None = field(default_factory=lambda: os.environ.get("PLATFORM_ADMIN_EMAIL"))
    platform_admin_password: str | None = field(default_factory=lambda: os.environ.get("PLATFORM_ADMIN_PASSWORD"))
    platform_admin_name: str = field(default_factory=lambda: os.environ.get("PLATFORM_ADMIN_NAME", "Platform administrator"))
    frontend_dist: str = field(default_factory=lambda: os.environ.get(
        "FRONTEND_DIST",
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")))
    run_migrations: bool = field(default_factory=lambda: _bool("RUN_MIGRATIONS", True))
    # AI assistant (any OpenAI-compatible chat API; Qwen on Alibaba Cloud Model Studio by default).
    ai_api_key: str | None = field(default_factory=lambda: os.environ.get("AI_API_KEY") or None)
    ai_base_url: str = field(default_factory=lambda: os.environ.get(
        "AI_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1").rstrip("/"))
    # A mid-priced model by default; set AI_MODEL to change it without a new release.
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", "qwen-plus"))
    ai_daily_limit: int = field(default_factory=lambda: int(os.environ.get("AI_DAILY_LIMIT", "50")))
    ai_timeout_s: int = field(default_factory=lambda: int(os.environ.get("AI_TIMEOUT_SECONDS", "60")))


settings = Settings()
