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


def create_app() -> FastAPI:
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

    # NOTE: dev-only convenience. Production uses Alembic migrations (M0+).
    Base.metadata.create_all(bind=engine)

    # Module routers are mounted here as they come online (M1+):
    #   from .modules.auth.routes import router as auth_router
    #   app.include_router(auth_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
