"""Application settings (env-driven). See .env.example."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "001"

    # Dev: SQLite for instant run. Production: PostgreSQL (30 users + pgvector).
    database_url: str = "sqlite:///./dev.db"

    secret_key: str = "dev-secret-change-me"
    host: str = "127.0.0.1"
    port: int = 8001
    secure_cookies: bool = False

    # Nightly backup scheduler — on in production, off in dev/tests.
    enable_scheduler: bool = False
    backup_dir: str = "backups"
    # Fleet work loop — how often the single loop drains the task queue (minutes).
    fleet_loop_minutes: int = 10
    # Mailbox root for the filesystem mail provider (inbox/ processed/ outbox/).
    # Real IMAP/SMTP providers are a private-deployment concern.
    mail_dir: str = "mailbox"
    mail_poll_minutes: int = 5

    # Dev bootstraps tables via create_all; production uses Alembic migrations.
    auto_create_tables: bool = True

    # AP 3-way match: allowed bill-vs-PO total variance, percent (0 = exact,
    # a 1-cent absolute floor always applies).
    ap_match_tolerance_pct: float = 0.0

    # Local AI (Phase 2) — Ollama runtime; model is swappable per deployment.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_embed_model: str = "bge-m3"
    ollama_vision_model: str = "qwen2.5vl:7b"  # invoice/document parsing
    # Context window. Smaller = less KV-cache memory so big models (32B) fit fully
    # in VRAM instead of spilling to CPU (which is ~20x slower). 8192 is plenty for
    # our prompt + history + tool results.
    ollama_num_ctx: int = 8192
    ai_max_tool_iters: int = 6


settings = Settings()
