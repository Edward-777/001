"""accounting module — COA, tax codes (M3); journal/posting engine (M4); AP (M10)."""
from . import ap_models  # noqa: F401  (register AP tables)
from . import ledger_models  # noqa: F401  (register ledger tables)
from . import models  # noqa: F401  (register master tables on Base.metadata)
