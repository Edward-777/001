"""FastAPI application factory — the single deployable process (modular monolith).

Run (after `pip install -e .`):
    uvicorn app.main:app --reload --port 8001
"""
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .core import Base, engine, settings

# Import models so their tables register on Base.metadata before create_all.
# (Each new module adds its models here — or a central registry later.)
from .core import audit as _audit  # noqa: F401
from .core import sequences as _sequences  # noqa: F401
from .modules import auth as _auth  # noqa: F401
from .modules import hr as _hr  # noqa: F401
from .modules import accounting as _accounting  # noqa: F401
from .modules import procurement as _procurement  # noqa: F401
from .modules import sales as _sales  # noqa: F401
from .modules import inventory as _inventory  # noqa: F401
from .modules import expense as _expense  # noqa: F401
from .modules import approval as _approval  # noqa: F401
from .modules import assets as _assets  # noqa: F401
from .modules import bank as _bank  # noqa: F401
from .modules import documents as _documents  # noqa: F401
from .modules import notifications as _notifications  # noqa: F401
from .modules import ai as _ai  # noqa: F401  (registers tools + conversation tables)
from .modules import fleet as _fleet  # noqa: F401  (registers fleet_tasks queue)


_DEFAULT_SECRET = "dev-secret-change-me"


def _check_production_config() -> None:
    """Refuse to boot with an unsafe production config (P0-5)."""
    if settings.secret_key == _DEFAULT_SECRET and (settings.secure_cookies or settings.enable_scheduler):
        raise RuntimeError(
            "SECRET_KEY is still the default. Set a real SECRET_KEY before "
            "running with secure_cookies/scheduler (production)."
        )


def create_app() -> FastAPI:
    _check_production_config()
    app = FastAPI(title=settings.app_name)

    # Session cookie auth (M1 builds login on top of this).
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        https_only=settings.secure_cookies,
        same_site="lax",
    )

    # Wire cross-module event handlers (procurement<-approval, accounting<-..., ...).
    from .wiring import register_all_handlers

    register_all_handlers()

    # Dev convenience: bootstrap the schema directly. Production runs the
    # Alembic baseline instead (`alembic upgrade head`); set auto_create=False.
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)

    # Module routers are mounted here as they come online (M1+):
    #   from .modules.auth.routes import router as auth_router
    #   app.include_router(auth_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    # Web UI (M15) + AI assistant (Phase 2)
    from .web.ai_routes import router as ai_router
    from .web.auth_routes import router as auth_router
    from .web.main_routes import router as main_router

    app.include_router(auth_router)
    app.include_router(main_router)
    app.include_router(ai_router)

    # Nightly backup scheduler (production only; off in dev/tests).
    if settings.enable_scheduler:
        from .core.scheduler import start_scheduler

        start_scheduler()

    return app


app = create_app()
