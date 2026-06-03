"""hr module — departments, employees, reports_to org chart.
Provides approval routing (M5) and the permission boundary resolver (DESIGN §8.5)."""
from . import models  # noqa: F401  (register tables on Base.metadata)
