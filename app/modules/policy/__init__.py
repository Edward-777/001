"""policy — the autonomy ladder's substrate.

An autonomy policy is a human-signed envelope: "within THESE bounds, the
system may execute without pre-approval (L3)." Policies are proposed as
drafts (by humans or AI), activated only by a human, revocable, versioned in
effect, and every evaluation leaves a decision record. If no policy matches,
the resolved ceiling is L2 — exactly today's behavior."""
from . import models, service  # noqa: F401
