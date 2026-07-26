# 001 — Enterprise AI Operating System

A fully-local AI operating system for running a company: AI agents execute the work
(finance, procurement, inventory, sales — with IT/HR and more to come), humans approve,
everything is audited. Sold as a single-tenant appliance bundled with server hardware.

## Docs
- **[docs/ADR.md](docs/ADR.md)** — architecture decision records: *why* it is built this way (start here if you're an engineer)
- **[OVERVIEW.md](OVERVIEW.md)** — one-page master summary
- [DESIGN.md](DESIGN.md) · [ROADMAP.md](ROADMAP.md)
- [docs/SCHEMA.md](docs/SCHEMA.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/POLICIES.md](docs/POLICIES.md) · [docs/AI-AGENT.md](docs/AI-AGENT.md)
- **[docs/AGENT-FLEET.md](docs/AGENT-FLEET.md)** — autonomous agent fleet (D6, in progress)

## Status
**Phase 1 COMPLETE (M0–M15)** — full accounting cycle (request → org-chart
approval → purchase → inbound → inventory ⇄ assets → outbound → sales/AR →
AP 3-way match → expense/reimbursement → bank reconciliation → financial
reports), all auto-booked via double-entry, with notifications, backup, and a
server-rendered HTMX/Tailwind UI.

**Phase 2 (AI agent) + Phase 3 (RAG / document parsing) COMPLETE** — local
Ollama agent over the service layer (tools obey the caller's permissions),
company-policy RAG, vision invoice parsing.

**D6 autonomous agent fleet (in progress)** — a single work loop turns inbound
work into role-drafted tasks the founder approves from an **Approval Inbox
(`/fleet`)**: 💸 vendor bills, 💰 customer invoices, 📦 supplier packing lists →
draft goods receipts, 📒 weekly payment runs & month-end close, ⚠️ anomaly
alerts, 📊 cash-runway insight (cash/burn/runway/"can we afford X"), and a full
**order-to-cash pipeline (`/sales`)** — quote → PO → ship (packing list) →
invoice, with downloadable customer documents. Everything is draft-only until a
human approves.

**Chat-first procure-to-pay (complete)** — vendor onboarding with W-9 attachment,
purchase requests from a product **link** (fetched locally, price as the
approver's double-check), org-chart approvals ("what do I need to approve?" →
approve/reject with reasons), **PO issuance + vendor-ready xlsx document**,
PO-validated receiving (over-receipt rejected, cost anchored to the PO), and a
**true 3-way match** (bill vs receipt vs PO) that never posts an exception.

**Agent architecture** — **plan-then-execute** with a visible step checklist
(template plans for known intents like month-end close; gated LLM planning
otherwise), **cross-conversation memory** written only by audited tool calls,
a **governed learning loop** (patterns mined from human resolutions become
rule proposals in the approval inbox; approved rules change behavior and count
their own applications), a per-reply execution timeline (tool · status ·
latency), and a deterministic honesty backstop so a failed action can never be
reported as a success. Why it's built this way: **[docs/ADR.md](docs/ADR.md)**.
**44 audited AI tools · 294 tests passing.**

## Setup (requires Python 3.12+)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy .env.example .env          # then edit
python -m scripts.seed_dev      # COA, rules, demo users
uvicorn app.main:app --reload --port 8001
#  -> http://127.0.0.1:8001/        login: admin@001.local / admin
pytest                          # 294 tests
```

> Dev uses SQLite for instant run. Production = PostgreSQL (set `DATABASE_URL`).
> Import real books from a QuickBooks Online export with `python -m scripts.import_qbo`
> (sets posting anchors + rules automatically).

## Layout
```
app/
  core/        # config, db, events (the spine), sequences, audit, base, scheduler
  modules/     # auth, hr, approval, procurement, inventory, assets, sales,
               # expense, bank, accounting, documents, ai, fleet
  web/         # routes + templates (dashboard, /fleet inbox, /sales O2C, ...)
  main.py      # FastAPI app factory (single process, modular monolith)
tests/
```
Each module = vertical slice: `service.py` is the only public entry point;
human UI (routes), AI (tools), and other modules all call it (ARCHITECTURE §2).
