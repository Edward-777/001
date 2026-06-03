# 001 — AI-native Local ERP

Lightweight, fully-local, AI-driven ERP for small businesses. Competes with QuickBooks;
sold as a single-tenant appliance bundled with server hardware.

## Docs
- **[OVERVIEW.md](OVERVIEW.md)** — one-page master summary (start here)
- [DESIGN.md](DESIGN.md) · [ROADMAP.md](ROADMAP.md)
- [docs/SCHEMA.md](docs/SCHEMA.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/POLICIES.md](docs/POLICIES.md) · [docs/AI-AGENT.md](docs/AI-AGENT.md)

## Status
**Phase 1 COMPLETE (M0–M15).** Full accounting cycle — request → org-chart
approval → purchase → inbound → inventory ⇄ assets → outbound → sales/AR →
AP 3-way match → expense/reimbursement → bank reconciliation → financial
reports — all auto-booked via double-entry, plus notifications, backup, and a
server-rendered HTMX/Tailwind UI. 100 tests passing.

## Setup (requires Python 3.12+)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy .env.example .env          # then edit
python -m scripts.seed_dev      # COA, rules, demo users
uvicorn app.main:app --reload --port 8001
#  -> http://127.0.0.1:8001/        login: admin@001.local / admin
pytest                          # 100 tests
```

> Dev uses SQLite for instant run. Production = PostgreSQL (set `DATABASE_URL`).

## Layout
```
app/
  core/        # config, db, events (the spine), sequences, audit, base
  modules/     # auth, hr, approval, procurement, inventory, assets,
               # sales, expense, bank, accounting, documents, ai
  main.py      # FastAPI app factory (single process, modular monolith)
tests/
```
Each module = vertical slice: `service.py` is the only public entry point;
human UI (routes), AI (tools), and other modules all call it (ARCHITECTURE §2).
