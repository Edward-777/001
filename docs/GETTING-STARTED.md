# Getting Started — operator setup

> How to install 001, stand up the AI runtime, and configure a company from
> zero. This is the operator's guide; day-to-day usage lives in
> [USER-GUIDE.md](USER-GUIDE.md), and moving existing books in lives in
> [MIGRATION.md](MIGRATION.md).

## 1. Prerequisites

| Piece | Requirement | Why |
|---|---|---|
| Python | 3.12+ | the app |
| Ollama | with `qwen2.5:14b`, `qwen2.5vl:7b`, `bge-m3` pulled | chat · vision (invoices/packing lists) · embeddings (RAG) |
| GPU | ~17 GB VRAM for all three models resident (24 GB card recommended) | a silent CPU fallback is ~20× slower |
| Database | none for dev (SQLite); PostgreSQL 16 for production | CI proves the fresh-Postgres install on every push |

**Always verify the AI runtime before first use:**

```bash
python -m scripts.preflight_ai
```

Every line must be `[OK]` and both models must show **100% GPU**. If you see
CPU residency, fix that before anything else (`docs/AI-OPS.md` covers the
known Ollama version pitfalls).

## 2. Install & run

```bash
python -m venv .venv && .venv/Scripts/activate    # or bin/activate
pip install -e ".[dev]"

# dev: instant seeded database (SQLite)
python -m scripts.seed_dev
uvicorn app.main:app --port 8001

# production: real database, migrations only
alembic upgrade head
```

Dev seed logins: `admin@001.local / admin` (full access) and
`alice@001.local / alice` (plain employee). `pytest` should pass 409 tests on
a healthy checkout.

Key settings (env vars or `.env`; see `app/core/config.py`):

| Setting | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./dev.db` | PostgreSQL URL in production |
| `SECRET_KEY` | dev value | **must** be changed in production |
| `ENABLE_SCHEDULER` | `false` | turns on nightly backups, fleet loop, alert ticks |
| `MAIL_ENABLED` | `false` | email intake/outbox ships dormant — leave off until the pre-launch live-mailbox test |
| `AP_MATCH_TOLERANCE_PCT` | `0.0` | allowed 3-way-match variance |

## 3. Set up your company (in this order)

Everything below can be done by the admin, most of it by just telling the
Assistant.

1. **Users & permissions.** Create users, set who reports to whom (approval
   routing follows the org chart). Permissions are 3-axis grants
   (scope × level × data boundary); roles apply sensible defaults —
   ADMIN/CFO get finance L3, an ACCOUNTANT gets finance L2 + sales L1, plain
   employees get self-service only.
2. **Chart of accounts.** A US small-business COA is seeded. Add or rename
   accounts to taste — posting rules are event-driven and survive renames.
3. **Vendors & customers.** Onboard by chat ("Register Acme Supplies,
   billing@acme.com, net 30") — the assistant never invents an EIN or email.
   Payment `remit_to` (bank details shown on payment instructions) and the
   autonomy allowlist tier are operator-level master data — set them
   deliberately, they gate money flows.
4. **Budgets.** Monthly budget per expense account ("set the 6300 budget to
   $500 a month") — budget-vs-actual and overrun alerts derive from postings.
5. **Compliance calendar.** One click on `/obligations` seeds the US basics
   (941, 940, 1099-NEC, 1120, WA B&O + L&I, DE franchise) with the right
   cadences; add company-specific duties by chat.
6. **Bank statements.** Import CSV/OFX from your cutover date; lines
   auto-match to existing entries and leftovers become questions, not
   guesses.
7. **Autonomy envelopes (optional, later).** Leave this OFF until the team
   trusts the drafts. When ready: `/policies` → propose an envelope (per-bill
   cap + daily cap + vendor allowlist), review, activate. Everything outside
   an envelope keeps parking for approval, and three rejected review cards
   suspend an envelope automatically.

**Migrating existing books?** Do step 1, then follow
[MIGRATION.md](MIGRATION.md) (cutover-date opening balances) before steps
2–6, since much of that data comes over with the migration.

## 4. Production notes

- Backups: nightly snapshots into `backup_dir` when the scheduler is on;
  test a restore before you need one.
- The fleet work loop, renewal/budget/deadline alerts, and month-close
  proposals all ride the same scheduler flag.
- The audit log, decision records, and reversal-only ledger are always on —
  they are not configurable, on purpose.
