"""Конфигурация из переменных окружения (.env). Секреты в коде не хранятся."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"  # development | production
    database_url: str = "sqlite+aiosqlite:///./autohunter.db"
    log_level: str = "INFO"

    # --- доступ к веб-панели ---
    auth_password: str = "change-me"
    auth_secret: str = "change-me-too"
    auth_token_ttl_hours: int = 24 * 7
    api_rate_limit_per_minute: int = 300

    # --- источники ---
    sources_enabled: str = "demo"  # через запятую: demo,apiad_avito,apiad_drom,autoru
    poll_interval_seconds: float = 20.0
    poll_jitter_seconds: float = 2.0
    request_timeout_seconds: float = 15.0
    max_backoff_seconds: float = 300.0
    demo_seed: int = 42
    demo_initial_listings: int = 450
    demo_live: bool = True  # генерировать «новые» объявления в демо-режиме

    apiad_api_key: str = ""
    apiad_base_url: str = "https://apiad.ru"
    apiad_queries: str = "BMW,Mercedes-Benz,Audi"  # поисковые запросы search_transport
    apiad_min_interval_seconds: float = 2.0
    autoru_api_key: str = ""

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_pairing_code: str = ""  # /start <код> регистрирует чат; пусто = регистрация выключена
    telegram_allowed_chat_ids: str = ""  # через запятую

    display_timezone: str = "Europe/Moscow"
    notify_max_age_hours: float = 12.0     # не уведомлять о «старых» объявлениях (бэкфилл)
    reprice_notify_pct: float = 5.0        # повторное уведомление при снижении цены не менее чем на N %

    # --- оценка и обслуживание ---
    listing_ttl_hours: int = 72
    revaluation_interval_minutes: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def enabled_sources(self) -> list[str]:
        return [s.strip() for s in self.sources_enabled.split(",") if s.strip()]

    @property
    def allowed_chat_ids(self) -> list[int]:
        return [int(x) for x in self.telegram_allowed_chat_ids.split(",") if x.strip().lstrip("-").isdigit()]

    def validate_for_production(self) -> list[str]:
        problems = []
        if self.is_production:
            if self.auth_password in ("", "change-me"):
                problems.append("AUTH_PASSWORD не задан (значение по умолчанию запрещено в production)")
            if self.auth_secret in ("", "change-me-too") or len(self.auth_secret) < 16:
                problems.append("AUTH_SECRET должен быть случайной строкой от 16 символов")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
