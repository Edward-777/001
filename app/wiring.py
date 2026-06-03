"""Central handler wiring — connects modules via the event bus at app startup.

Each module exposes register_handlers(); we call them here. Idempotent so it's
safe to call more than once (e.g. app factory + tests).
"""
from __future__ import annotations

_registered = False


def register_all_handlers(*, force: bool = False) -> None:
    global _registered
    if _registered and not force:
        return

    from .modules.accounting.handlers import register_handlers as accounting
    from .modules.procurement.handlers import register_handlers as procurement

    procurement()  # approved purchase request -> draft PO
    accounting()   # inbound posted -> journal entry
    # future modules: assets (inbound asset -> FixedAsset), sales, expense, bank

    _registered = True
