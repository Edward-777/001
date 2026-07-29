# 001 — Enterprise AI Operating System

![tests](https://github.com/Edward-777/001/actions/workflows/ci.yml/badge.svg)

> **Traditional ERP asks humans to operate accounting software.**
> **001 lets AI agents operate the business system — while humans keep approval and control.**

![18-second highlights: the agent plans and closes the month, refuses a payment order embedded in a document, and drafts work a human approves](docs/img/demo.gif)

**[▶ Watch the 2-minute demo](docs/demo/demo-2min.mp4)** — the agent closing the
books, being denied by the permission gate, refusing prompt injection, drafting
under maker-checker, and learning a rule under human governance.

This repository is a **working reference implementation** of an AI-native
enterprise operating system: the core architecture and the representative
business flows, implemented end to end and tested. It is not a packaged
product — the scope is deliberate (see [Scope](#scope-what-this-repo-is-and-isnt)).

**At a glance**

- **58 permission-aware AI tools** — every tool is a thin wrapper over the same
  service layer the human UI calls, constrained by the caller's permissions and
  re-checked at execution
- **358 automated tests** (CI also proves a fresh-PostgreSQL install from
  migrations alone) plus a **live-model behavior battery** — six axes, two
  languages, honest results ([docs/EVAL.md](docs/EVAL.md))
- **Procure-to-pay and order-to-cash, end to end** — through chat, with real postings
- **Double-entry accounting** — event-driven posting, US GAAP conventions, month-end close
- **Autonomous agent fleet** — drafts work from inbound documents; only humans post
- **Human approval and audit trail on every consequential action**
- **Fully local AI** (Ollama: chat + vision + embeddings) — **no business data
  is sent to a cloud LLM; all model inference runs locally**

---

## The three flows that prove it

### Demo 1 — Procure-to-Pay (chat-first)

```
natural-language purchase request
→ AI tool execution (draft — maker-checker gated)
→ org-chart approval        → purchase order (+ vendor document)
→ PO-validated receiving    → vendor invoice (vision-parsed)
→ true 3-way match          → posting to the ledger → payment (SoD)
```

"Close June 2026" — the agent plans, executes each step through
permission-checked tools, and returns the closing package:

![Plan-then-execute: month-end close with a visible step checklist and per-tool execution timeline](docs/img/plan-then-execute.png)

### Demo 2 — Order-to-Cash

```
quote → customer acceptance (PO) → shipment (packing list, stock issue + COGS)
→ AR invoice (revenue recognition) → receipt
```

Every stage produces a downloadable customer document; every posting is an
automatic double-entry journal.

### Demo 3 — Autonomous Fleet

```
agent detects work (uploaded invoice, packing list, anomaly, renewal, budget overrun)
→ task in the work queue → role agent drafts (never posts)
→ Approval Inbox (/fleet) → human approves → posting + audit trail
```

A document that orders the AI to wire money is refused — guardrails are code,
not prompts:

![An instruction embedded in an uploaded invoice is treated as untrusted data and refused](docs/img/guardrails-injection.png)

The system also **learns under governance**: rules mined from human decisions
are proposed in the same approval inbox — never applied silently:

![A learned vendor-alias rule proposed as an approval card](docs/img/learning-loop.png)

---

## Why this isn't an AI wrapper

The LLM is never a security boundary and never a source of record:

- **Permission inheritance** — 3-axis gate (scope × level × data boundary)
  applied identically to UI, AI tools, and RAG retrieval; re-checked at
  execution (defense in depth)
- **Maker-checker** — an AI-created money draft cannot be submitted in the same
  turn; a human confirms the figures
- **Honesty backstop** — a failed tool call is stamped into the data the model
  reads back; a failure can never be reported as a success
- **Prompt-injection defense** — document content is data, not instructions
- **Draft-first fleet** — autonomous agents produce drafts; the approval inbox
  is the single control point for posting
- **Derived, never stored** — PTO used, budget actuals: always computed from
  the source records, so reports cannot drift from the books
- **Audit everything** — every AI tool call, approval, and posting lands in the
  audit log; the ledger allows reversing entries only

## Architecture

The system ships a live map of its own runtime at `/map` — every box is real
code in this repo, every number is queried from the database at render time:

![Runtime map: inputs → local-model AI runtime → guardrail membrane → human decision → system of record, with the memory and learning feedback loops](docs/img/runtime-map.png)

A **modular monolith**: 17 vertical-slice modules (auth, hr, approval,
procurement, inventory, assets, sales, expense, bank, accounting, documents,
ai, fleet, learning, leave, contracts, budget). Each module exposes its
business operations through `service.py`; human routes and AI tools share
those same service functions — so the AI has no privileged path — while
selected read-side and relational integrations reference domain models
directly. Cross-module posting is event-driven: inventory announces "a
receiving happened"; only accounting knows which accounts that posts to. Details:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · design rationale with the
incidents that drove it: [docs/ADR.md](docs/ADR.md).

## Documentation

| Document | What it answers |
|---|---|
| [PRODUCT_VISION.md](PRODUCT_VISION.md) | Why this exists, what AI-native means, where it's going |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | What works today, verified, with numbers |
| [ROADMAP.md](ROADMAP.md) | What's next (and what's deliberately out of scope) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module map, event spine, dependency rules |
| [docs/ADR.md](docs/ADR.md) | 11 architecture decision records — the WHY, with live incidents as evidence |
| [docs/SCHEMA.md](docs/SCHEMA.md) | Every table, with the modeling decisions |
| [docs/EVAL.md](docs/EVAL.md) | Live-model behavior battery: method, results, what it caught |
| [docs/AI-OPS.md](docs/AI-OPS.md) | Running local models reliably (GPU pinning, VRAM budget) |

Earlier design-time documents are preserved in [docs/archive/](docs/archive/).

## Setup (requires Python 3.12+)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy .env.example .env          # then edit
python -m scripts.seed_dev      # COA, rules, demo users
uvicorn app.main:app --reload --port 8001
#  -> http://127.0.0.1:8001/        login: admin@001.local / admin
pytest                          # 358 tests
```

Dev uses SQLite for instant run. Production targets PostgreSQL — a fresh
database installs from the migration chain alone (`alembic upgrade head`),
which CI verifies against PostgreSQL 16 on every push. Existing books can be
imported from a QuickBooks Online export with `python -m scripts.import_qbo`.

Local models (via [Ollama](https://ollama.com)): `qwen2.5:14b` (chat),
`qwen2.5vl:7b` (vision), `bge-m3` (embeddings). Verify GPU residency with
`python scripts/preflight_ai.py` before use — a silent CPU fallback is about
20x slower.

## Scope — what this repo is (and isn't)

This is the **reference architecture layer**: the structures that make an
AI-operated business system trustworthy (permission inheritance, maker-checker,
draft-first autonomy, governed learning, derived reporting) implemented and
tested on the representative flows above.

Deliberately **not** in the public scope: payroll and tax execution (regulated
— integrate, don't rebuild), live bank feeds and payment rails, installer and
appliance provisioning, production data-migration tooling (a limited reference
importer for QuickBooks Online exports **is** included; migration and
reconciliation tooling for real customer books is not), per-industry
accounting rule packs, provider-specific connector deployments and credential
management (generic intake interfaces stay public), and production evaluation
datasets. Those belong to a deployment layer, not to the reference architecture.

## Layout

```
app/
  core/        # config, db, events (the spine), sequences, audit, base, scheduler
  modules/     # auth, hr, approval, procurement, inventory, assets, sales,
               # expense, bank, accounting, documents, ai, fleet, learning,
               # leave, contracts, budget
  web/         # routes + templates (dashboard, /fleet inbox, /sales O2C, ...)
  main.py      # FastAPI app factory (single process, modular monolith)
tests/
```

## Author

Built by Edward Kim, Bellevue, WA. I've spent my career running the business
side of companies — accounting, treasury, procurement, HR, IT — and built this
solo to see how much of that work AI can run.

Contact: edwardjk919@gmail.com
