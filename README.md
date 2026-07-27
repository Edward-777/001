# 001 — Enterprise AI Operating System

![tests](https://github.com/Edward-777/001/actions/workflows/ci.yml/badge.svg)

**Finance · Procurement · Inventory · Sales — run by AI agents, approved by
humans, audited end to end. Fully local LLMs (Ollama), zero cloud calls.**

A fully local system where AI agents run a company's operations — finance,
procurement, inventory, sales — through the same permission-checked service
layer as the human UI. Humans approve every consequential action. Everything
the system does, including what it learns, is audited.

Runs as a single-tenant appliance: the application, the database, and all
three models (chat, vision, embeddings) live on the customer's own hardware.
No data leaves the machine.

"Close June 2026" — the agent plans, executes each step through
permission-checked tools, and returns the closing package:

![Plan-then-execute: month-end close with a visible step checklist and per-tool execution timeline](docs/img/plan-then-execute.png)

A document that orders the AI to wire money is refused — guardrails are code,
not prompts:

![An instruction embedded in an uploaded invoice is treated as untrusted data and refused](docs/img/guardrails-injection.png)

The system mines rules from human decisions and proposes them in the same
approval inbox — learning is never applied silently:

![A learned vendor-alias rule proposed as an approval card](docs/img/learning-loop.png)

## Documentation

- [docs/ADR.md](docs/ADR.md) — architecture decision records: why the system
  is built this way. Start here if you are an engineer.
- [OVERVIEW.md](OVERVIEW.md) — one-page summary
- [DESIGN.md](DESIGN.md) · [ROADMAP.md](ROADMAP.md)
- [docs/SCHEMA.md](docs/SCHEMA.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
  [docs/POLICIES.md](docs/POLICIES.md) · [docs/AI-AGENT.md](docs/AI-AGENT.md) ·
  [docs/AGENT-FLEET.md](docs/AGENT-FLEET.md)

## What works today

**Accounting core.** Double-entry ledger, event-driven posting rules, US GAAP
conventions, moving-average inventory costing, straight-line depreciation,
GR/IR clearing, period close and locking, and a nine-sheet month-end closing
package generated on demand. Reports: balance sheet, income statement, cash
flow, trial balance, general ledger, journal entries, AP/AR aging, inventory
valuation, cash runway.

**Chat-first procure-to-pay.** Vendor onboarding with document attachment
(e.g. a W-9), purchase requests from a pasted product link (the page is
fetched locally and the extracted price is flagged for the approver to
verify), org-chart approvals handled in conversation, purchase-order issuance
with a vendor-ready document, PO-validated receiving (over-receipts are
rejected, costs anchor to the approved PO), a true three-way match — bill vs
receipt vs PO — where an exception can never post, and payment with
segregation of duties between bill entry and payment.

**Autonomous agent fleet.** Inbound documents are classified and parsed by a
local vision model, then drafted into work a human approves from a single
inbox: vendor invoices become draft bills (PO-matched when the invoice names
one), supplier packing lists become draft goods receipts, plus weekly payment
runs, month-end close, and anomaly alerts (spend spikes, duplicate bills).

**Agent architecture.** Plan-then-execute with a visible step checklist
(template plans for known intents such as month-end close; gated LLM planning
otherwise), cross-conversation memory written only by audited tool calls, a
governed learning loop (patterns mined from human decisions become rule
proposals in the approval inbox; approved rules change behavior and count
their own applications), a per-reply execution timeline (tool, status,
latency), and an honesty backstop so a failed action can never be reported as
a success.

**Order-to-cash.** Quote, customer PO, shipment with packing list, invoice —
each stage producing a downloadable customer document.

44 audited AI tools. 295 tests.

## Setup (requires Python 3.12+)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy .env.example .env          # then edit
python -m scripts.seed_dev      # COA, rules, demo users
uvicorn app.main:app --reload --port 8001
#  -> http://127.0.0.1:8001/        login: admin@001.local / admin
pytest                          # 295 tests
```

Dev uses SQLite for instant run. Production targets PostgreSQL (set
`DATABASE_URL`). Existing books can be imported from a QuickBooks Online
export with `python -m scripts.import_qbo`.

Local models (via [Ollama](https://ollama.com)): `qwen2.5:14b` (chat),
`qwen2.5vl:7b` (vision), `bge-m3` (embeddings). Verify GPU residency with
`python scripts/preflight_ai.py` before use — a silent CPU fallback is about
20x slower.

## Layout

```
app/
  core/        # config, db, events (the spine), sequences, audit, base, scheduler
  modules/     # auth, hr, approval, procurement, inventory, assets, sales,
               # expense, bank, accounting, documents, ai, fleet, learning
  web/         # routes + templates (dashboard, /fleet inbox, /sales O2C, ...)
  main.py      # FastAPI app factory (single process, modular monolith)
tests/
```

Each module is a vertical slice: `service.py` is the only public entry point.
Human routes, AI tools, and other modules all call the same service functions,
so the AI never has a privileged path (see ADR-1).
