"""fleet — the autonomous agent orchestration layer (docs/AGENT-FLEET.md).

A single work loop pulls from the `tasks` queue and processes each item as its
assigned role (a config of prompt+tools+permissions), drafting work that the
founder approves. This module owns the queue + dispatcher + loop; the roles
themselves act through existing module services (accounting, sales, ...).
"""
from . import models  # noqa: F401  (register fleet_tasks)
