# 001 — Roadmap (Phase 1 detail)

> Work-unit breakdown of the [OVERVIEW.md](OVERVIEW.md) roadmap. Build order = **dependencies + "spine first"** principle.
> Principle: stand up the **spine** first (scaffold → permissions → accounting core + posting → one vertical event slice) to prove the architecture, then fan out to the remaining modules.

---

## Phase 1 — Lightweight Core (full accounting cycle, manual operation without AI)

| M | Milestone | Key deliverables | Acceptance criteria (done) |
|---|---|---|---|
| **M0** | Project scaffold | repo structure, config, DB session, **event bus**, base models, doc_sequences, audit_log, app factory, /health | Boots via `uvicorn` with /health returning 200. Event bus unit tests pass |
| **M1** | Auth + three-axis permissions | users, user_scopes, session login, **permission gate** (scope × level × boundary decision function) | Login works. Permission decision function tests (including the salary = hr3 blocking case) |
| **M2** | HR / org chart | departments, employees, reports_to | Employee registration and reporting-line tree. `get_approval_chain()` works |
| **M3** | Master data + COA seed | vendors, customers, products, accounts (+ QuickBooks COA seed), lookups (categories/tax) | COA seed loads. CRUD works |
| **M4** | **Accounting core + posting engine** (key milestone) | journal_entries/lines (debit = credit invariant), configurable posting rule table, accounting_periods (closing) | Manual journal posting, reversal, and closing work. Posting rule unit tests |
| **M5** | Approval workflow | requests, approval_lines, approval_rules, **org-chart routing engine** | Draft → submit → automatic org-chart approval chain → approve/reject |
| **M6** | Procurement (spine slice) | purchase_orders (created from an approved request) | Approval → automatic PO creation |
| **M7** | **Inventory + event integration proof** (key milestone) | inbounds, stock_movements/balances (moving average), serials. `InboundPosted` event → automatic accounting journal | Receiving posted → inventory updated **+ automatic journal entry** (same transaction). Architecture validated |
| **M8** | Assets | fixed_assets, depreciation, **inventory ↔ asset conversion** | Asset receiving, monthly depreciation, bidirectional conversion journals |
| **M9** | Shipping + sales/AR | outbounds, sales_orders, ar_invoices, receipts | Sales shipment (COGS) + AR invoice (revenue, tax) + receipt journals |
| **M10** | AP 3-way match | ap_bills, ap_bill_lines, payments | PO ↔ receiving ↔ invoice matching, GR/IR clearing, payment |
| **M11** | Expense reimbursement | requests (type=expense) extension + reimbursement | Travel expense → approval → reimbursement liability → payment |
| **M12** | Bank reconciliation | bank_accounts, statement upload (parser is manual/CSV first), reconcile | Statement line ↔ journal matching, new journal for unmatched lines |
| **M13** | Reports | BS/IS/CF/TB/GL/AP·AR aging/inventory valuation (derived from journals) | "January close package" = generate_financials works |
| **M14** | Cross-cutting | notifications + SSE, documents registry (pre-AI), nightly backups | Real-time approval notifications, backup and restore |
| **M15** | UI | HTMX/Jinja2/Tailwind screens (lists, forms, dashboard), responsive/PWA | A person can run the full cycle through the screens |

**Phase 1 definition of done:** without AI, a person can run the entire cycle — *request → approval → purchase → receiving → inventory/assets → shipping → sales/AR → expenses → bank reconciliation → closing → financial statements* — through the screens, and every transaction lands in the books via automatic double-entry.

---

## Phase 2+ (summary)
- **P2 agent hookup — Done:** Ollama + tool registry + agent loop. Permission gates, uncertainty gating. Business-trip scenario.
- **P3 document parsing, classification, RAG — Done:** inbound classification pipeline (§8.4), permission-filtered RAG queries, vision invoice parsing.
- **GTM onboarding (partial):** QBO export import (`scripts/import_qbo` — COA + journals, posting anchors/rules auto-seeded). Opening balances and AI account mapping to follow.
- **P4 fine-tuning:** behavior LoRA + eval harness + dataset/eval versioning. (Not started.)

---

## D6 — Autonomous Operations Agent Fleet (in progress)

> Design and implementation details = [docs/AGENT-FLEET.md](docs/AGENT-FLEET.md). `fleet` module + `/fleet` and `/sales` screens.

| Milestone | Content | Status |
|---------|------|------|
| F1 | Work queue (`fleet_tasks`) model + state machine (dedup, bounce-back, escalation) | Done |
| F2 | Dispatcher (classification → role routing) | Done |
| F3 | Spend/AP role handler + single work loop (draft → approve → post) | Done |
| F4 | Approval inbox UI + upload → dispatcher + APScheduler tick | Done |
| F5 | Treasury/Insights (runway, burn rate, headroom) + AI tools | Done |
| F6 | Revenue/Collections role (customer invoice draft → approve → revenue recognition) | Done |
| F7 | Weekly payment run → payment journal on approval | Done |
| F8 | Anomaly detection (spend spikes, duplicates) + daily inbox notification | Done |
| F9 | Month-end close proposal → period lock on approval | Done |
| F10 | Insights dashboard cards + inbox counts | Done |
| F11–13 | Order-to-cash (O2C): quote and shipment models + fulfillment service + documents (quote/packing/invoice) + `/sales` pipeline UI | Done |
| — | Email connector (Gmail OAuth) · optional roles (people/docs/support) · classifier expansion | Follow-up |
| Done | Supply role (packing list → receiving draft) · chat P2P complete (vendor onboarding, link-based requests, PO issuance, PO receiving, true 3-way) · plan-then-execute · cross-conversation memory · **governance learning loop** (vendor alias mining, ADR-10) | 2026-07-24 |

**Invariants:** all roles always available (a single loop switches roles as it works) · draft-first · consequential actions (posting, payment, sending, closing) are gated behind human approval · zero company data leaves the box.

**Code-review hardening (from external review):** all fleet mutation routes behind the finance L3 gate · documents Default-Deny (classification failure → most restrictive) · single source of truth for report perms · per-JE balance assertion in the importer · graceful LLM failure. **Follow-ups = eval harness · approval fatigue mitigation (risk-sorted inbox) · regenerate Alembic migrations.**

---

## The Logic Behind the Build Order (why this sequence)
1. **M0–M1** (scaffold, permissions) are *the prerequisite for everything*. Retrofitting permissions later means rewriting everything → do it from the start.
2. **M4, the accounting core + posting engine, is the center of gravity.** Every subsequent module fires events into it.
3. **M7** is the first end-to-end pass of "receiving → event → automatic journal" → **proof that the architecture (event + posting decoupling) actually runs.** Once this passes, the remaining modules replicate the same pattern.
4. UI (M15) comes thin, after service is fully in place — service is the source of truth, so UI can wait.
