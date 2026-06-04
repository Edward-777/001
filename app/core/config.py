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

    # Nightly backup scheduler — on in production, off in dev/tests.
    enable_scheduler: bool = False
    backup_dir: str = "backups"

    # Dev bootstraps tables via create_all; production uses Alembic migrations.
    auto_create_tables: bool = True

    # Local AI (Phase 2) — Ollama runtime; model is swappable per deployment.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_embed_model: str = "bge-m3"
    ai_max_tool_iters: int = 6


settings = Settings()
