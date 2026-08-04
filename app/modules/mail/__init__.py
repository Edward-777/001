"""mail — email as an intake surface (and, later, an outbound channel).

Half of a company's work arrives by email. This module turns a mailbox into
the same governed pipeline every other intake uses: parse → match the sender
to master data → classify → dispatch a DRAFT task to the fleet. Email content
is untrusted data end to end — it can create drafts for human approval, never
side effects."""
from . import models, provider, service  # noqa: F401
