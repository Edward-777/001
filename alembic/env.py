"""Alembic environment — wired to the app's Base.metadata and settings URL.

Imports every module's models (NOT app.main, which would create_all) so
autogenerate sees the full schema (P1-5)."""
from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core import audit as _audit  # noqa: F401
from app.core import sequences as _sequences  # noqa: F401
from app.core.config import settings
from app.core.db import Base

# Register every module's models on Base.metadata (no create_all side effect).
# MUST match app/main.py's import list — tests/test_migrations.py enforces it.
from app.modules import (  # noqa: F401
    accounting,
    ai,
    approval,
    assets,
    auth,
    bank,
    budget,
    contracts,
    documents,
    expense,
    fleet,
    hr,
    inventory,
    learning,
    leave,
    mail,
    notifications,
    procurement,
    sales,
)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url, target_metadata=target_metadata,
        literal_binds=True, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
