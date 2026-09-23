"""Application settings, loaded from environment / .env (see .env.example for the full list).

Every setting has a dev-safe default so the app boots locally with zero configuration beyond
`cp .env.example .env`. Production deployments override via real environment variables — never
by editing this file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "ci", "staging", "production"] = "local"

    database_url: str = "postgresql+asyncpg://pfa:pfa@postgres:5432/pfa"
    redis_url: str = "redis://redis:6379/0"

    secret_key_id: str = "dev"
    jwt_private_key_path: str = "./dev-keys/jwt_ed25519"
    kms_provider: Literal["local", "aws", "gcp"] = "local"
    local_kek_base64: str = ""
    phone_hash_pepper: str = ""

    telephony_provider: Literal["fake", "plivo"] = "fake"
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""

    stt_provider: Literal["fake", "deepgram"] = "fake"
    deepgram_api_key: str = ""

    llm_provider: Literal["fake", "gemini"] = "fake"
    gemini_api_key: str = ""
    llm_model_incall: str = "gemini-flash"
    llm_model_postcall: str = "gemini-flash"

    tts_provider: Literal["fake", "cartesia"] = "fake"
    cartesia_api_key: str = ""

    livekit_url: str = "ws://livekit:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "pfa-audio"

    email_provider: Literal["smtp"] = "smtp"
    smtp_url: str = "smtp://mailpit:1025"

    test_allowlist_e164: str = Field(default="", description="Comma-separated E.164 numbers.")

    platform_max_concurrent_calls: int = 50
    dnd_strict: bool = True

    public_base_url: str = "http://localhost:8000"
    dashboard_base_url: str = "http://localhost:3000"

    sentry_dsn: str = ""

    @property
    def test_allowlist(self) -> list[str]:
        return [n.strip() for n in self.test_allowlist_e164.split(",") if n.strip()]

    def validate_startup(self) -> None:
        """Refuse to boot on dangerous provider/environment combinations (PFA-SYS-010)."""
        if self.app_env != "production":
            if self.telephony_provider == "plivo" and not self.test_allowlist:
                raise RuntimeError(
                    "PFA-SYS-010: TELEPHONY_PROVIDER=plivo requires a non-empty "
                    "TEST_ALLOWLIST_E164 outside production."
                )
        else:
            fake_providers = {
                "telephony": self.telephony_provider == "fake",
                "stt": self.stt_provider == "fake",
                "llm": self.llm_provider == "fake",
                "tts": self.tts_provider == "fake",
            }
            if any(fake_providers.values()):
                bad = ", ".join(k for k, v in fake_providers.items() if v)
                raise RuntimeError(f"PFA-SYS-010: fake providers not allowed in production: {bad}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
