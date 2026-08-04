"""payments — instructions, not transfers.

The system never moves money. It prepares a payment instruction — who to pay,
where, how much, under which reference, with the full evidence chain — and a
human executes the transfer at the bank. Only after the human confirms the
execution (date + bank reference) does the payment journal post. The books
record what actually happened, never what the system wishes had happened."""
from . import models, service  # noqa: F401
