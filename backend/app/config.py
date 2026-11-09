from decimal import Decimal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SANDBOX_URL = "https://api-m.sandbox.paypal.com"


class Settings(BaseSettings):
    database_url: str = "sqlite:///./verdict.db"
    api_token: str = "verdict-demo-token"
    frontend_origin: str = "http://localhost:3000"
    auto_seed: bool = True

    paypal_mode: str = "mock"
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_webhook_id: str | None = None
    paypal_base_url: str = SANDBOX_URL
    # Secret used by the built-in simulator to sign webhook payloads (mock mode only).
    webhook_sim_secret: str = "verdict-sim-secret"

    llm_provider: str = "mock"
    groq_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_s: int = 30
    llm_max_retries: int = 2
    # Max amount the LLM may move the deterministic checklist score (+/-).
    llm_adjustment_limit: float = 0.15

    stage_delay_ms: int = 0
    action_max_retries: int = 2

    auto_refund_cap: Decimal = Decimal("100.00")
    approval_threshold: Decimal = Decimal("250.00")
    fight_min_win_likelihood: float = 0.60
    refund_max_win_likelihood: float = 0.35
    min_confidence: float = 0.70
    urgent_hours: int = 24

    # Impact panel assumptions (modeled, not measured).
    modeled_minutes_per_case: int = 25

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    @field_validator("paypal_client_id", "paypal_client_secret", "paypal_webhook_id", "groq_api_key", mode="before")
    @classmethod
    def clean_pasted_secret(cls, value: object) -> object:
        """Hosts and .env files often add spaces, quotes or a trailing newline to pasted keys."""
        if isinstance(value, str):
            return value.strip().strip("\"'").strip() or None
        return value

    @model_validator(mode="after")
    def validate_integrations(self) -> "Settings":
        if self.paypal_mode not in {"mock", "sandbox"}:
            raise ValueError("PAYPAL_MODE must be mock or sandbox")
        if self.paypal_base_url != SANDBOX_URL:
            raise ValueError(f"PAYPAL_BASE_URL must be {SANDBOX_URL}")
        if self.paypal_mode == "sandbox" and (not self.paypal_client_id or not self.paypal_client_secret):
            raise ValueError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required when PAYPAL_MODE=sandbox")
        if self.llm_provider not in {"mock", "groq"}:
            raise ValueError("LLM_PROVIDER must be mock or groq")
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return self


settings = Settings()
