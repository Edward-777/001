"""obligations — the company's time axis.

Tax deadlines, annual reports, license renewals, labor-law filings: all the
same shape (a date + a duty + evidence + an owner), all missed the same way
(nobody was watching). One table watches all of them; recurring duties
re-create their next occurrence when completed, so the calendar never runs
dry."""
from . import models, service  # noqa: F401
