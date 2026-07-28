"""contracts — the commitments register: subscriptions, leases, insurance,
service agreements. Tracks end dates and notice windows so a renewal (or an
auto-renewing subscription that should be canceled) never arrives as a surprise."""
from . import models, service  # noqa: F401
