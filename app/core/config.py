"""Application settings (env-driven). See .env.example."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "001 ERP"

    # Dev: SQLite for instant run. Production: PostgreSQL (30 users + pgvector).
    database_url: str = "sqlite:///./dev.db"

    secret_key: str = "dev-secret-change-me"
    host: str = "127.0.0.1"
    port: int = 8001
    secure_cookies: bool = False


settings = Settings()
