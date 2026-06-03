"""The single permission gate (DESIGN §8.5) — used identically by human UI,
AI tools, and RAG retrieval. There is exactly ONE decision rule:

    access  ⟺  user.level[scope] >= required_level
              AND subject is within user's data_boundary

Boundaries self/all are decided here. team/department need the org-chart
(reports_to) tree, supplied by an injected resolver (HR module, M2). Until a
resolver is wired, team/department DEFAULT-DENY (fail closed — DESIGN §8.4).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import DataBoundary

# resolver(actor_employee_id, subject_employee_id, boundary) -> bool
BoundaryResolver = Callable[[int, int, DataBoundary], bool]


@dataclass(frozen=True)
class ScopeGrant:
    level: int
    data_boundary: DataBoundary


class Forbidden(Exception):
    """Raised by require_access. At the AI layer this becomes a polite refusal;
    crucially the data is never fetched (DESIGN §8.3 tool gate)."""


def can_access(
    grants: dict[str, ScopeGrant],
    scope: str,
    required_level: int,
    *,
    subject_employee_id: int | None = None,
    actor_employee_id: int | None = None,
    boundary_resolver: BoundaryResolver | None = None,
) -> bool:
    grant = grants.get(scope)
    if grant is None or grant.level < required_level:
        return False

    # Not a per-subject record -> scope+level is enough.
    if subject_employee_id is None:
        return True

    boundary = grant.data_boundary
    if boundary == DataBoundary.ALL:
        return True
    if boundary == DataBoundary.SELF:
        return subject_employee_id == actor_employee_id
    # team / department
    if boundary_resolver is None:
        return False  # Default-Deny until org-chart resolver is wired (M2)
    return boundary_resolver(actor_employee_id, subject_employee_id, boundary)


def require_access(
    grants: dict[str, ScopeGrant],
    scope: str,
    required_level: int,
    **kwargs,
) -> None:
    if not can_access(grants, scope, required_level, **kwargs):
        raise Forbidden(f"requires {scope} level {required_level}")
