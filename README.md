# 001 — AI-native Local ERP

Lightweight, fully-local, AI-driven ERP for small businesses. Competes with QuickBooks;
sold as a single-tenant appliance bundled with server hardware.

## Docs
- **[OVERVIEW.md](OVERVIEW.md)** — one-page master summary (start here)
- [DESIGN.md](DESIGN.md) · [ROADMAP.md](ROADMAP.md)
- [docs/SCHEMA.md](docs/SCHEMA.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/POLICIES.md](docs/POLICIES.md) · [docs/AI-AGENT.md](docs/AI-AGENT.md)

## Status
**Phase 1 / M0 — project scaffold.** Core infrastructure (config, DB, event bus,
doc numbering, audit log, app factory) in place. Modules build per ROADMAP.md.

## Setup (requires Python 3.12+)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy .env.example .env          # then edit
uvicorn app.main:app --reload --port 8001
#  -> http://127.0.0.1:8001/health
pytest                          # run tests (event bus, ...)
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
