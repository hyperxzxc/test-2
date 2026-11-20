from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./keitaro.db"
    keitaro_base_url: str = "https://tlgk.host"
    keitaro_api_key: SecretStr = SecretStr("")
    keitaro_timeout: float = 15
    default_domain_id: int | None = None
    default_group_id: int | None = None
    default_traffic_source_id: int | None = None
    app_access_token: SecretStr = SecretStr("")
    frontend_dir: Path = Path("frontend/dist")
    demo_mode: bool = False

    @field_validator(
        "default_domain_id", "default_group_id", "default_traffic_source_id", mode="before"
    )
    @classmethod
    def empty_id(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("keitaro_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.query:
            raise ValueError("Expected an HTTP(S) tracker origin without credentials or query")
        if url.path.rstrip("/") not in {"", "/admin_api/v1"}:
            raise ValueError("Use the tracker origin or /admin_api/v1 URL")
        return value.rstrip("/").removesuffix("/admin_api/v1")

    @field_validator("keitaro_timeout")
    @classmethod
    def bounded_timeout(cls, value: float) -> float:
        if not 0 < value <= 30:
            raise ValueError("Timeout must be between 0 and 30 seconds")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
