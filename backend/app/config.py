from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./verdict.db"
    api_token: str = "verdict-demo-token"
    frontend_origin: str = "http://localhost:3000"
    paypal_mode: str = "mock"
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_webhook_id: str | None = None
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    llm_provider: str = "mock"
    groq_api_key: str | None = None
    llm_model: str = "llama-3.3-70b-versatile"
    llm_timeout_s: int = 30
    llm_max_retries: int = 2
    stage_delay_ms: int = 0
    auto_refund_cap: Decimal = Decimal("100.00")
    approval_threshold: Decimal = Decimal("250.00")
    fight_min_win_likelihood: float = 0.60
    refund_max_win_likelihood: float = 0.35
    min_confidence: float = 0.70

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
