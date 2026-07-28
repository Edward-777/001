# 001 — Module Architecture Design

## 0. Ground Rules

- **Modular monolith.** No microservices — that directly violates the lightweight principle.
  → Deployment is a **single process**; internally, **strictly separated modules**. Keep the boundaries clean so a module can be split out later if ever needed.
- **Key insight:** we already committed to a "tool-first (agentic core)" design. That means **each module's public service API = the single entry point called by both humans (UI) and AI (tools)**. Modularization and AI tooling are *the same work*.

---

## 1. Module Map

| Module | Responsibility | Key API exposed to other modules |
|---|---|---|
| **core** | DB session, **event bus**, config, money/decimal, audit log, base models | (infrastructure — everyone depends on it) |
| **auth** | Users, sessions, roles, permissions | `get_current_user`, `has_permission` |
| **hr** | Employees, organization, **reporting lines (reports_to)** | `get_approval_chain(employee_id)`, `get_employee` |
| **approval** | Approval requests, rules, **routing engine** | `submit_request`, `approve`, `reject` |
| **procurement** | Vendors, purchase orders (PO) | `create_po`, `get_po` |
| **inventory** | Products, stock, receiving, shipping, serials, **moving average** | `post_inbound`, `post_outbound`, `get_stock` |
| **assets** | Fixed assets, depreciation, **inventory ↔ asset conversion** | `create_asset`, `run_depreciation`, `reclassify` |
| **sales** | Customers, sales orders (SO), AR invoices, receipts + **O2C fulfillment** (quote → PO → shipment → invoice), documents | `create_so`, `post_ar_invoice`, `post_receipt`, `fulfillment.*`, `documents.*` |
| **expense** | Expenses / reimbursement (Non-PO spend), employee refunds | `submit_expense`, `reimburse` |
| **bank** | Bank accounts, **monthly statement upload reconciliation** | `import_statement`, `reconcile` |
| **accounting** | COA, journals, periods (closing), AP (3-way), payments, **posting engine**, financial statements | `post_journal`, `generate_financials`, `match_ap_bill` |
| **documents** | Attachments, OCR/parsing | `store_document`, `parse_document` |
| **ai** | Agent orchestrator, **tool registry**, LLM (Ollama), RAG, conversations | (calls other modules' tools) |
| **fleet** | Autonomous operations orchestration: work queue (`fleet_tasks`), dispatcher, **single work loop**, role handlers, approval inbox (D6) | `service.*` (queue), `dispatcher.dispatch`, `loop.run_once`, `roles.resolve` |
| **learning** | Governed learning loop: rules mined from human resolutions, human-approved, applied deterministically (ADR-10) | `resolve via procurement.resolve_vendor`, `miner.*` |
| **leave** | PTO balances (granted only; used derived from requests), manager-approved leave via reports_to, onboarding checklist | `request_leave`, `approve_leave`, `balance`, `start_onboarding` |
| **contracts** | Commitments register: subscriptions/leases/insurance, renewal notice windows → INSIGHT inbox card | `add_contract`, `upcoming_renewals`, `end_contract` |
| **budget** | Monthly budget per expense account; actuals derived from posted journals; overruns → INSIGHT inbox card | `set_budget`, `budget_vs_actual`, `consumption_note` |

> **Dependency direction rule:** dependencies flow top → bottom only. Accounting knows nothing about inventory (reverse direction forbidden). Inventory doesn't call accounting directly either → **connected via events** (§3 below).
> **fleet is the top-level orchestrator** — it calls other modules' services to draft role-specific work, and posts after human approval. Details = [AGENT-FLEET.md](AGENT-FLEET.md).

---

## 2. Module Internal Structure (identical skeleton for every module)

```
inventory/
  __init__.py     # module registration: routes + event handlers + AI tools
  models.py       # PRIVATE — other modules must never import this
  schemas.py      # DTOs (Pydantic) — public contract types
  service.py      # PUBLIC API — the only external entry point
  events.py       # events this module publishes
  handlers.py     # subscribes and reacts to other modules' events
  tools.py        # AI tools (thin wrappers over service.py)
  routes.py       # UI/HTTP (thin — calls service only)
```

**Iron rules:**
1. Neither `routes` nor `tools` touches `models` directly → always go through `service`.
2. Outside a module, **nobody looks at another module's `models.py`/tables directly.** Only that module's `service.py` functions + `schemas.py` DTOs.
3. `service.py` is the module's "API specification". (Humans = routes call it, AI = tools call it, other modules = call it directly — **the same functions**.)

---

## 3. Cross-Module Integration — Two Mechanisms

The one rule that keeps integration unambiguous:

> **When you *need* something fetched or done = direct service call** (you know the counterpart)
> **When something *happened* and you don't care who reacts = publish an event** (you don't know the counterpart)

### (A) Synchronous call — Command / Query

When you know which module you're talking to. Example: approval routing needs the org chart →
```python
# approval/service.py
chain = hr.service.get_approval_chain(drafter_employee_id, levels=2)
```
- Exchanged via typed DTOs. Querying the other module's tables directly is forbidden.

### (B) Domain events — Reaction (the heart of the accounting integration)

When *money moves* in inventory/assets/procurement, that module **just publishes an event without knowing who listens**. Accounting subscribes and creates the journal entry.

```
inventory.post_inbound()  ─emit→  InboundPosted{lines:[{product_type, qty, cost}]}
                                        │
                  ┌─────────────────────┼──────────────────────┐
            accounting.handlers      assets.handlers       (audit/RAG indexing…)
            → creates journal          → asset-type lines
              via posting engine         auto-register a FixedAsset
```

**Why this is decisive:** the inventory module **knows zero GL account codes.** Only the accounting module knows "which transaction posts to which account". Inventory only announces "a receiving happened". → Touching inventory/procurement/assets doesn't break accounting logic, and changing accounting rules leaves inventory code untouched.

**Transaction boundary:** events are **dispatched synchronously within the same DB transaction**. Receiving + journal + asset registration commit **all-or-nothing**. (No async queue like Celery/Redis needed — stays lightweight, consistency guaranteed.)

> **Clarification (read vs post):** "accounting knows nothing about inventory" is a principle scoped to **automatic posting** only. Only the direction where accounting receives domain events and *creates journals* is decoupled via events. Conversely, **intentional command/query reads of domain data by accounting are allowed** — AP 3-way match (querying received quantities) and reports (inventory valuation, receivables) are examples. Reads create no cycle (domains never import accounting), so they are safe.

---

## 4. Posting Engine — the Single Point of Accounting Integration

**One rule table** that every automatic journal entry passes through. Account-mapping knowledge lives here and only here.

| event_type | Condition (product_type etc.) | Debit | Credit |
|---|---|---|---|
| inbound.posted | inventory | Inventory | GR/IR |
| inbound.posted | asset | Fixed Asset | GR/IR |
| ap_bill.matched | — | GR/IR | AP |
| outbound.posted | sale | COGS | Inventory |
| reclass | inv→asset | Fixed Asset | Inventory |
| reclass | asset→inv | Inventory + Accumulated Depreciation | Fixed Asset |
| depreciation.run | — | Depreciation Expense | Accumulated Depreciation |
| ar_invoice.posted | — | AR | Revenue + Sales Tax Payable |
| receipt.posted | — | Bank/Cash | AR |
| expense.approved | per category | Expense account | Employee Payable |
| reimburse.posted | — | Employee Payable | Cash |
| bank.unmatched | per category | Fees/Interest etc. | Bank |

- **Table-driven (configurable)** → an admin can change account mappings without code changes. Keeps flexibility for replacing QB.
- The AI also goes through this engine, so AI-created journals follow **exactly the same rules** as human-created ones.

---

## 5. How the AI Layer Sits on Top

```
        ┌────────────── ai module (orchestrator) ──────────────┐
        │  conversation → LLM (Ollama) → tool selection → tool execution → response │
        └──────────────────────┬──────────────────────────────┘
                               │ tools = each module's tools.py
                               ▼
   inventory.tools / accounting.tools / approval.tools / hr.tools ...
                               │ (thin wrappers)
                               ▼
                  each module's service.py  ← UI (routes) calls the same thing
```

- **Tool registry:** each module registers its tools in `tools.py` → the `ai` module collects them → provided to the LLM as function schemas.
- Adding a new feature = add a function to service + one registration line in tools → **the human UI and the AI gain the feature simultaneously**.
- **Uncertainty gating (§8.2)** and audit logging are applied uniformly at the ai orchestrator + service level.

---

## 6. One-Page Summary

1. Single process, strictly separated internals (modular monolith).
2. A module's only door = `service.py`. Direct access to others' models is forbidden.
3. Integration: **direct call when you need something / event when you're reacting**.
4. Accounting attaches **only via event subscription + the posting rule table** → fully decoupled.
5. AI tools = thin wrappers over service → humans and AI share the same API.
6. Events dispatch synchronously in the same transaction → consistency and lightness at once.
