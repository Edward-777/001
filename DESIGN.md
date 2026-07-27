# 001 — AI-native ERP — Design Document

> **Status:** v0.1 (living document)
> **Started:** 2026-06-02
> **How to use this document:** Decisions made in conversation accumulate here. "Undecided" marks items still under discussion, "Done" marks agreed items. This document comes before the code.

---

## 1. Vision

An ERP for solo founders and small startups that runs **on the desktop, without internet, driven directly by AI**.

The existing production ERP (Flask+PostgreSQL, ~90k LOC, Redis/Celery/Nginx/Docker) is **enterprise-grade heavy**. This project borrows its domain knowledge but is a **complete, lightweight rebuild from scratch**.

**Endgame:** *Running the company entirely through conversation, with no gaps.* Travel requests are just one example. Hiring, purchasing, receiving, accounting, inventory, assets — every business process should be handled in natural language.

**The competitor is QuickBooks.** The goal is a **whole-company ERP that is easier, lighter, and usable without specialist knowledge** — better than QB. Not just accounting: **inventory, assets, and SCM must be solid** too (QB is accounting-centric and weak there — that is our differentiator).

Example flows:
- *"I'm going to a conference May 1–15"* → AI asks follow-ups → drafts the request → **org-chart-based approval routing** → approval → handoff.
- Attach an invoice PDF → AI reads it → 3-way match against PO and receipt → AP and journal entry created automatically.
- *"New hire OOO, assign to team X"* → AI registers the employee → future approval lines form automatically from the org placement.

---

## 2. Goals / Non-Goals

### Goals
- **Ultimate goal: replace QuickBooks.** The accounting module is not a mere helper but a **complete bookkeeping system** (double-entry GL + AP/AR + financial statements + bank reconciliation + 1099), so that eventually the books can be closed on this system alone, without QB.
- **Lightweight**: target ~1/5 the code of the existing system. Single process, double-click-to-run simplicity.
- **Fully local**: data and AI both local. Zero external API dependencies (optional only).
- **Connected business chain**: request → purchasing → inventory → assets → accounting flows naturally through data.
- **AI-native**: humans and AI invoke the *same business tools*.
- Ship as a **desktop app**.

### Non-Goals (deliberately excluded — the essence of staying lightweight)
- No multi-tenancy / multi-org (single organization assumed)
- No distributed infrastructure (Redis/Celery/Nginx/Docker/message queues)
- No OAuth/SSO/external IdP (session-cookie local auth is enough). However, **authorization itself is sophisticated** — the 3-axis model (§8.5). "Simple authentication, sophisticated authorization."
- No high availability / horizontal scaling (single user to a handful)
- No cloud dependency (optional only)

---

## 3. Design Principles

1. **Tool-first (agentic core)** — every business action is defined as an explicit function ("tool"). Humans invoke them via UI, AI via function calls — *the same tools*. This is the spine of the entire design.
2. **The core stands alone** — domain logic runs and is tested without UI or AI.
3. **Simplicity beats features** — if it isn't used, don't build it. No god-files, no over-abstraction.
4. **Data is truth** — every business flow leaves traceable data (including audit logs). This later becomes the basis for training our own model.
5. **Local first, cloud optional** — local by default. Cloud is an option that can be turned off.

---

## 4. Personas & Scope

- **Scope baseline:** a typical small startup. (Generic — not tied to any specific company.)
- **Done — Country: United States.** → Accounting is **US GAAP**, currency **USD**, taxes are **sales/use tax** (no Korean-style tax invoices or VAT). Vendor 1099s; possible book (straight-line) vs. tax (MACRS) depreciation split. UI language defaults to **English** (D14). The legacy system imported QuickBooks accounts, so alignment with a **QuickBooks-style chart of accounts (COA)** is recommended.
- **Primary users:** founder/operators. Accounting, purchasing, and approval roles may overlap in one person.
- **Done — User count: at most 30 true concurrent users.** → Not "a desktop app per person" but **one host (GPU box) as the server + 30 people connecting via browser**. The LLM has to run on a single 4090, so this shape is natural. The "desktop app" is optional packaging for that host.
- **Done — 30 concurrent → PostgreSQL** (avoids SQLite's single-writer lock). Still a single server, still lightweight.
- **Done — Network: intranet only. External access goes through VPN into the internal network.** → The app is never exposed to the public internet. The security boundary is the VPN. Session + roles are sufficient at the app layer.
- **Done — Mobile/tablet access does not violate "local".** Definition of "local" = **data is stored and processed inside the customer's box (never transits a third-party cloud)**, not "single device only". Phones/tablets are just more browser clients. The AI still runs on the appliance's 4090 → "talking to the ERP from your phone" is still local.
  - On-site = LAN browser / off-site = enter via VPN (WireGuard), then connect (data stays in the box; only traffic is encrypted).
  - **Responsive UI (Tailwind built in) + PWA** (add-to-home-screen, app-like experience) is enough → **no native app needed**, single codebase.
  - For remote access: HTTPS even on the LAN, 2FA recommended for remote.

---

## 5. Domain Model — the Business Chain (core)

> This section is where the "modules don't connect" problem gets solved. Below is a draft skeleton, to be detailed in upcoming conversations.

```
[Request/Draft]  Request/Draft
     │  submit
     ▼
[Approval]       Approval ──(approved)──┐
     │                                  │
     ▼                                  ▼
[Purchasing]     PurchaseOrder    (ends if rejected)
     │  receive
     ▼
[Inventory]      Inventory (in/out, quantity & unit cost)
     │  capitalize / consume
     ├──────────────┐
     ▼              ▼
[Assets]       [Cost/Expense]
 FixedAsset    Cost/Expense
     │              │
     └──────┬───────┘
            ▼
[Accounting]  JournalEntry → financial statements
```

### 5.1 Entity Map (draft — Note: the current source of truth is [docs/SCHEMA.md](docs/SCHEMA.md))

> The list below is the early skeleton. **The current canonical schema (~40 tables, including HR, sales/AR, expenses, banking, document classification, and onboarding) lives in SCHEMA.md.** Use this map for the big picture only.

**Master data**
- `User` — name, email, password hash, role, department, active flag
- `Department` — department (for approval routing and aggregation)
- `Vendor` — purchasing counterparty
- `Customer` — sales counterparty (whether it is in Phase 1 = D10)
- `Product` — item: type (stock/asset/consumable/service), unit, category, standard price
- `Account` — chart of accounts: code, name, type (asset/liability/equity/revenue/expense)

**Workflow (requests/approvals)**
- `Request` — request/proposal: type (purchase/expense/travel/general), requester, title, body, amount, status (draft→submitted→approved/rejected→closed)
- `ApprovalLine` — approval line: request_id, approver, sequence, status, decision date, comment
- `ApprovalRule` — approval rule: amount and type → approval line auto-construction

**Purchasing**
- `PurchaseOrder` — purchase order (created from an approved Request): vendor, status (ordered→partially_received→received→closed)
- `POLine` — PO line: product, quantity, unit price, amount

**Inventory**
- `StockMovement` — inventory movement: product, type (inbound/outbound/adjustment), quantity, unit cost, source (PO/issue/adjustment)
- `StockBalance` — on-hand stock: per-product quantity + average unit cost (moving average)
- `Outbound` — issue: consumption/sale/production input

**Assets**
- `FixedAsset` — fixed asset (created when a received item is an asset): acquisition cost, acquisition date, useful life, depreciation method, accumulated depreciation, status
- `DepreciationEntry` — depreciation records (monthly)

**Accounting (where every flow converges)**
- `JournalEntry` — journal entry: date, memo, source (PO receipt/asset/payment/manual), status (draft→posted)
- `JournalLine` — line: account, debit, credit (total debits = total credits enforced)
- `APBill` — accounts payable / `Payment` — payment
- (`ARInvoice`/`Receipt` — sales side, per D10)

### 5.2 Automatic Integration Rules (← the key to solving "modules don't connect")

On each stage transition, **the next stage's data plus the accounting entry are generated automatically**:

| Trigger | Auto-created | Auto journal entry |
|--------|-----------------|----------------|
| Request **approved** | PurchaseOrder | — |
| PO **received** (Inbound) | StockMovement(+), StockBalance updated | Dr Inventory/Expense, Cr Accounts Payable (AP) |
| Received item is an **asset** | FixedAsset registered | Dr Fixed Assets, Cr Accounts Payable |
| **Payment** | APBill settled | Dr Accounts Payable, Cr Cash/Bank |
| Month-end **depreciation** | DepreciationEntry | Dr Depreciation Expense, Cr Accumulated Depreciation |
| **Issue** (consumption/sale) | StockMovement(−) | Dr COGS/Expense, Cr Inventory |

> In other words, users only perform **business actions** like "request → approve → receive"; **the system books the journal entries automatically**. The ledger stays correct without any accounting knowledge. That is the real value of an ERP for solo/small teams.

### 5.3 Settled Accounting/Inventory Policies
- **Done — Full double-entry auto-posting** (debits = credits, chart of accounts, journal entries → BS/IS financial statements). US GAAP.
- **Done — Both purchasing and sales sides in Phase 1.** (The purchasing side was designed first, but per decision G1 AR/sales is also in Phase 1 — see §10.5.) Sales/AR = customers, sales orders, invoices, receipts.
- **Done — Inventory valuation = moving average** (average unit cost updated on every receipt). Abstracted so FIFO can be added later.
- **Done — USD currency, sales/use tax regime** (no VAT, no tax invoices).

### 5.4 Additional Settled Policies
- **Done — UI language = English by default** (i18n scaffolding in place; Korean added later)
- **Done — Depreciation = book straight-line only.** Tax MACRS is design-ready but deferred / delegated to a CPA.

### 5.5 Field-Level Schema
- Done — D13: **[docs/SCHEMA.md](docs/SCHEMA.md)** covers the full cycle with ~40 tables (purchasing, inventory, assets, conversions, accounting, periods/reports, sales/AR, banking, expenses, document classification, permissions, onboarding). Q1–Q6 all settled.

---

## 6. Architecture — 4 Layers

| Layer | Role | Notes |
|----|------|------|
| **1. Domain core** | Entities + business "tool" functions | Runs and is tested without UI/AI |
| **2. Local API** | Exposes tools via function call/HTTP | Shared by human UI and AI |
| **3-A. Human UI** | Screens (forms/lists/dashboards) | Local web → desktop packaging |
| **3-B. AI agent** | Natural language → tool calls, document parsing, data queries (RAG) | Local LLM |

Principle: 3-A and 3-B **share layer 2**. The AI is "another user who presses buttons by talking."

---

## 7. Tech Stack — Done: recommended and confirmed

The combination that satisfies 30 users + lightweight + AI-native + fully local:

| Area | Choice | Rationale |
|------|------|------|
| **Language/core** | Python 3.12 | Reuses existing accounting domain knowledge, team familiarity, AI ecosystem |
| **API framework** | **FastAPI** | Lightweight; function signatures → auto schemas → **directly enables AI tooling** (best fit for the tool-first principle) |
| **DB** | **PostgreSQL** | Safe concurrent writes for 30 users. Single instance, so still lightweight (no Redis/Celery). Abstracted via SQLAlchemy |
| **App server** | uvicorn multi-worker (no gunicorn) | Handles 30 concurrent users. Single machine |
| **ORM / migrations** | SQLAlchemy 2.0 + Alembic | Standard, easy DB swap |
| **UI** | **Server-rendered HTMX + Jinja2 + Tailwind** | Ideal for 30 LAN-browser users. No build pipeline, Python only, perfect for a form/list-heavy ERP. Much lighter than React |
| **AuthN/AuthZ** | Session cookie + **3-axis permissions (§8.5)** | Authentication is simple (sessions); authorization is scope×level×boundary. Roles = employee/manager/accountant/admin |
| **Desktop packaging** | (host only) **pywebview**, optional | The 30 users connect via browser; only the host is packaged as an app |
| **Background jobs** | **APScheduler** (in-process) | Approval notifications etc. No Celery/Redis |
| **Real-time notifications** | FastAPI SSE | "Approval arrived" push. Simpler than WebSocket |
| **Local LLM runtime** | **Ollama** (OpenAI-compatible API) | Runs on the 4090, supports tool calling |
| **LLM model** | **Swappable**. Dev = Qwen2.5 (4090); ship = both Llama 3.3 70B and Qwen2.5-72B installed, customer picks | Details → [docs/AI-AGENT.md](docs/AI-AGENT.md) |
| **Vector search (RAG)** | **pgvector** (Postgres extension) | Vectors in the same DB. No separate vector DB |

> The essence: **PostgreSQL + a single Python (FastAPI) server + Ollama**. Redis, Celery, Nginx, Docker — **all unnecessary** (add later if desired). That is what "lightweight" actually means here.

---

## 8. Local AI Design

> Agent mechanics (model, tools, loop, RAG) are detailed in **[docs/AI-AGENT.md](docs/AI-AGENT.md)**. This §8 covers governance (training, autonomy, permissions, classification, input gating).

- **Hardware:** RTX 4090 (development) / high-end sales server (production). Model is swappable (§AI-AGENT 1).
- **Document parsing:** vision model or OCR+LLM — invoice/statement/receipt PDFs → automatic accounting and reconciliation.
- **Data queries (RAG):** ERP data embedded → pgvector → permission-filtered search → natural-language answers.

### 8.1 AI Training Strategy (important — correcting a common misconception)

"Fine-tune daily on each day's incoming documents" is **the wrong tool for the job**. For AI to run a company it needs **two distinct capabilities**, each obtained differently:

| Capability needed | Examples | Correct method |
|---|---|---|
| **Fresh facts** | Today's inventory, this month's invoices, team X's approver | **RAG + direct DB queries (tools)** — *never fine-tuning*. Query the live DB. Always current, no training needed, no hallucination |
| **Operating behavior** | Our company's approval conventions, posting rules, tone, tool-usage patterns | **Periodic LoRA fine-tuning** — learn *how we work* from accumulated interaction logs |

- Note: **never fine-tune daily to make the model "memorize" new documents.** Facts are the job of RAG/tools (always accurate and current). Fine-tuning is for *behavior and capability*, and **weekly/monthly cadence** is enough.
- Done — **Fully local = data never leaves.** Fine-tuning also runs locally on the 4090. Privacy is solved structurally.
- Note — **Regression risk:** every tuning run can break things, so an **eval harness is mandatory.** Automatically verify "is it no worse than before" on every tuning run. (This is the core of trust.)
- **Stages:** (1) strong open model + tool calling + RAG (zero training) → (2) periodic behavior LoRA tuning (once data accumulates) → (3) guard with evals.

### 8.2 AI Autonomy Policy (D18)

Trustworthy autonomy = **automatic execution + uncertainty gating + periodic audit**:

1. **Auto posting** — the AI takes journal entries all the way to **posted**, not just draft. Humans do not approve every entry (otherwise "run the company by conversation" doesn't hold).
2. **Uncertainty gating** — when the AI is unsure (e.g., which account, which PO to match), it **does not proceed automatically; it asks the submitter.** It only auto-executes when things are clear.
3. **Periodic audit** — weekly/monthly, a human reviews the AI's entries and documents and corrects as needed. Corrections become training data for behavior tuning (§8.1).
4. **Every AI action is audit-logged** (who/what/source document) and traceable. (§3 principle 4)

### 8.3 AI Permission & Data Access Model (the biggest AI-native security issue)

Problem: someone without authorization asks "hey, what's xxx's salary?" and the LLM might just answer.

**Iron rule: the LLM is not a security boundary. Permission checks happen deterministically in code *below* the model.**
- Wrong: telling the model via prompt "don't reveal sensitive info" → defeated by jailbreaks, confusion, or mistakes. Not security.
- Right: **data the caller cannot access never enters the model's context in the first place.**

**Three-layer defense:**
1. **Identity:** the AI agent **inherits the asker's session/permissions** and acts as that person (impersonation). "An all-seeing admin AI deciding what to reveal" — no.
2. **Tool gate:** every service function checks `current_user` permissions → **Forbidden** if insufficient (the data itself is never returned). The G11 permission matrix applies as-is. The AI never receives the numbers → responds "not authorized."
3. **Retrieval gate (easy to miss):** RAG applies **permission filters at retrieval time**. Documents/rows carry ACL tags (e.g., `hr_confidential`) → without permission they are **excluded from search = absent from context.** Filter **before retrieval**, not "generate then filter" (once something is in context, a prompt can't block it).

**Additionally:** sensitive-data classification (salary, SSN, banking, performance reviews = higher clearance only), all queries and denials recorded in audit_logs, a natural refusal UX when blocked, and prompt guardrails only as a *secondary* defense.

> Effect: **the same AI, same question yields different results depending on the asker's permissions.** Without authorization, the information the AI can give is structurally zero.

### 8.4 Inbound Document Classification Pipeline (the premise of the retrieval gate = a core system axis)

The retrieval gate (3) stands on **the premise that document ACL tags are accurate**. One misclassification = security breach. So **"classify at intake" is the starting point of all access control.** The same classification also drives automation → a core component.

```
(1) Capture → (2) Extract (OCR/text) → (3) Classify (local AI) → (4) Gate → (5) Tag → (6) Route → (7) RAG index
(3) Classification outputs: category (invoice/statement/receipt/contract/payroll/resume/PO…) + sensitivity/ACL + linked entities (vendor, customer, employee, period, amount)
```
- **Dual purpose:** classification = who can see it (security) + what gets auto-processed (routing). E.g., invoice → AP draft + accounting permission; payroll → HR permission + HR flow.
- **Iron rule 1 — Default-Deny:** when sensitivity is uncertain, **default-tag at the most restrictive level** and then confirm. Misclassification must *always fail closed* (too open = leak; too closed = an access request).
- **Iron rule 2:** sensitive categories (payroll, contracts) never auto-pass — human confirmation required. Re-tagging is possible; corrections become behavior-tuning data.

### 8.5 Permission Model — 3 Axes (scope × level × data boundary)

A simple hierarchy (employee < manager < accountant < admin) is not enough. Real permissions are the **product of three axes**:

| Axis | Question | Example |
|---|---|---|
| **(1) scope (domain)** | Which area? | hr / finance / inventory / system |
| **(2) level (grade)** | How deep within it? | hr 1 (basic) / 2 (sensitive, performance reviews) / 3 (executive, salaries) |
| **(3) data_boundary** | Whose data? | self / team / department / all |

**HR example (staff / manager / director):**
```
Staff (hr)    : level=1, boundary=self        → org chart, own info
Manager (hr)  : level=2, boundary=team        → team performance reviews yes, salaries (lvl3) no
Director (hr) : level=3, boundary=department  → department salaries yes, other departments no
HR exec/admin : level=3, boundary=all
```
- Data/documents carry a **`(scope, level)` tag** plus the linked employee. "Salary" = `(hr,3)`.
- **Decision formula:** `user.level[scope] >= data.level` **AND** `target is within user's data_boundary`.
- **Axis (3) comes free from the org chart:** self/team/department is decided by subtree membership in the `reports_to_id` tree → the approval org chart is reused for row-level access control. Minimal new structure.
- Lightweight implementation: a small `user_scopes(user_id, scope, level, data_boundary)` table + the single formula above. Roles grant default scope bundles, adjusted per person (lightweight RBAC + clearance + ReBAC). Applied **identically** to UI, AI, and RAG.

**A system-wide principle (not HR-specific):** the same 3-axis formula applies to **every domain**. finance (1 expense requests / 2 AP·AR / 3 ledger & financial statements), inventory (1 view / 2 in-out / 3 valuation & adjustments), procurement (1 request / 2 PO / 3 contracts), system (admin)… The staff/manager/director structure from HR works identically across all modules.
- **Single gate, every path:** human UI, AI tools, RAG retrieval, API/reports **all pass through the same formula**. If a person can't see it on screen, they can't see it via AI, search, or API either (zero leak paths).
- **Fits the module architecture:** all access goes through the single service entry point, so putting the gate in the service protects the whole system. Adding a module = adding one scope; permission code unchanged.
- **Prerequisite:** because it applies globally, **every sensitive datum/document must carry a `(scope,level)` tag** → which is why §8.4 "auto-classify at intake" is a core axis. Classification → tag → permission is one chain.

### 8.6 Input Gate — Relevance & Quality (blocking junk and inaccurate data)

Problem: what if employees dump in irrelevant junk or inaccurate data? Handle the two kinds separately.

**Iron rule: nothing enters the live system or RAG before passing classification (quarantine).** Input goes to quarantine first → only what passes classification and validation is promoted.

**(a) Irrelevant data:**
1. **Category-mapping failure = rejection** — if it matches no known business category (invoice, statement, receipt, contract, HR…), quarantine as 'uncategorized'; no indexing, no routing.
2. **Default-Not-Indexed** — data is not RAG-indexed by default. Only "promoted-to-official records" get indexed → junk structurally cannot enter RAG.
3. **Ask back** — when ambiguous, don't swallow it; confirm with the uploader (reusing §8.2). No response → purge.

**(b) Inaccurate data:**
4. **Per-category validation rules** — expenses require amount/date/receipt; invoices require vendor/amount/period. Flag omissions and outliers.
5. **Deduplication** — detect and block re-uploads of the same invoice.
6. **Human confirmation for sensitive/critical categories** (§8.4).

**Malicious input (prompt injection):** document text is **always treated as data, never interpreted as instructions.** Retrieved content is sandboxed. The permission gate (§8.5) still applies regardless → injection cannot cross permissions.

> **Why it matters:** garbage accumulating in RAG degrades retrieval quality and **poisons later behavior tuning (garbage in, garbage out).** The input gate protects the wellspring of AI quality. (Note: *unauthorized* input is already blocked by §8.5 — this section handles *relevance and accuracy*.)

---

## 9. Roadmap (Phases)

| Phase | Contents | Deliverable |
|-------|------|--------|
| **1. Lightweight core (full cycle)** | Domain model + tools + UI. Manual operation without AI: request → org-chart approval → purchasing → receiving → inventory ⇄ assets → issue, **plus sales/AR, expense reimbursement, bank reconciliation, accounting periods/reports**. 3-axis permissions, numbering, audit, backup | A working ERP skeleton |
| **2. Agent hookup** | Local LLM calls the tools. Travel scenario. Permission gate, uncertainty gating | An ERP that "does what you say" |
| **3. Document parsing + queries + classification** | Automatic invoice/statement/receipt processing, intake classification pipeline, permission-filtered RAG queries | AI assistant |
| **GTM. Onboarding/migration** | Master-data import + opening balances + AI account mapping (for selling to existing customers) | Commercial release |
| **4. Self fine-tuning** | Behavior LoRA on accumulated data + eval harness | Company-specific LLM |

> Note that Phase 1 is **the full accounting cycle**, not "purchasing side only" (reflecting decisions G1–G3). GTM = go-to-market.

---

## 10. Open Decisions Log

| # | Item | Status |
|---|------|------|
| D1 | Project name | Done: **001** |
| D2 | User count | Done: max 30 (concurrent vs. registered distinction is D8) |
| D3 | Tech stack | Done: recommendation confirmed (§7) — awaiting final user sign-off |
| D4 | Domain entity details (fields/states/transition rules) | In progress (§5 draft written) |
| D10 | Sales/AR in Phase 1 | Done: purchasing side first, AR in Phase 1.5 |
| D11 | Accounting depth | Done: full double-entry auto-posting (US GAAP) |
| D12 | Inventory valuation | Done: moving average |
| D13 | Field-level entity detail + state diagrams | Undecided ← next task |
| D14 | UI language | Done: English default (i18n scaffolding ready) |
| D15 | Depreciation | Done: straight-line only (MACRS later) |
| Country | United States (US GAAP, USD, sales tax) | Done |
| D5 | Local LLM model selection | Partial: designed → [docs/AI-AGENT.md]. Recommended Qwen2.5-14B (default) / 32B (quality). Only the 14 vs. 32 user choice remains |
| D6 | Permission/auth level (role split) | Done: session + roles (requester/approver/admin) |
| D7 | Reuse of existing code | Done: **no reuse** (dated code; clean slate) |
| D16 | HR/org-chart module | Done: **included** (employees + reporting lines, foundation for approvals) |
| D17 | SCM/inventory depth | Done: simple in/out + moving average. **Model name + serial #** tracking (sale stock and assets). No multi-warehouse/BOM/production |
| D18 | AI autonomy | Done: **AI auto-posting** + asking back when uncertain + weekly/monthly human audit and correction |
| Data migration | Migration | Done: **none** (clean-slate start) |
| D8 | Meaning of "30 users" → DB | Done: 30 concurrent → **PostgreSQL** |
| D9 | Deployment/network | Done: one host + browsers, **intranet + VPN** |

---

## 10.5 Design Gap Review (2026-06-02) — Open

Gaps found from an architect's perspective after the architecture was completed. Things that cannot be missing given the QB-replacement goal.

**A. Structural — direction must be set now (affects schema/modules)**
| # | Gap | Notes |
|---|---|---|
| G1 | **AR/sales** (customers, sales orders, customer invoices, receipts, customer aging) | Done: **in Phase 1**. Mirror structure of the purchasing side |
| G2 | **Bank & cash + bank reconciliation** | Done: included. **Method = monthly statement upload → AI extracts descriptions → reconcile** (no live feeds; fully local). A use case for local-AI document parsing |
| G3 | **Expense reimbursement (non-PO spend, employee reimbursements)** | Done: **in Phase 1**. The endpoint of the travel example |
| G4 | **Opening balances / migration** | Note: for our own use = start from zero (unnecessary). **BUT mandatory for a commercial product** → migrating existing customers (QB etc.) = **onboarding milestone**: master-data import + cutover-date opening balances (→ Opening Balance Equity) + open AP/AR/inventory/asset as-of seeding + **AI parses QB exports and maps accounts**. Phase = go-to-market |

**B. Domain additions — can be deferred to later phases**
| # | Gap | Notes |
|---|---|---|
| G5 | Returns (purchase returns / sales returns) | Inventory + accounting reversal entries |
| G6 | Physical inventory count / adjustment | Count variances, damage, write-downs |
| G7 | Payroll | Scope? Manual JE vs. integration |
| G8 | Budget control | Budget check at purchase request (can be skipped for small teams) |

**C. Policy/detail — small but global**
| # | Gap | Notes |
|---|---|---|
| G9 | Posted-entry correction policy | Done: no deletion — **reversal entries only**. Closed periods locked. Audit log → [POLICIES.md] |
| G10 | Document numbering | Done: PREFIX-YYYY-NNNN per type, gapless (allocated inside the transaction) |
| G11 | Permission matrix | Done: 4 roles (employee/manager/accountant/admin). Expense requesters get no GL access. AI inherits the caller's permissions |
| G12 | Notifications | Done: in-app notification center + SSE real-time. Email optional |
| G13 | Backup/restore | Done: nightly pg_dump + uploads, 7 daily / 4 weekly / 12 monthly rotation, one-click restore |

> Full detail for group C → [docs/POLICIES.md](docs/POLICIES.md)

## 11. Decision Log (Decisions Made)

- **2026-06-02** — Rebuild the new system *from scratch, lightweight*. The existing ERP is reference only. (Scope: typical small startup, desktop app, fully local, RTX 4090.)
- **2026-06-02** — Core design principle = **tool-first (agentic core)**. Humans and AI call the same tools.
- **2026-06-02** — Project name **001**. Max 30 users → direction set as one host server + LAN browsers.
- **2026-06-02** — Tech stack confirmed (§7): Python + FastAPI + **PostgreSQL** + SQLAlchemy + HTMX/Jinja2/Tailwind + session auth + APScheduler + Ollama + pgvector. No Redis/Celery/Nginx/Docker.
- **2026-06-02** — 30 concurrent users → PostgreSQL. Intranet + VPN access (no public exposure).
- **2026-06-02** — **US market**: US GAAP, USD, sales/use tax (no VAT), QuickBooks-style COA recommended. Accounting = full double-entry auto-posting, purchasing side first (AR = Phase 1.5), inventory = moving average.
- **2026-06-02** — UI English by default (i18n ready), depreciation straight-line only. AP = **3-way match** (PO ↔ receipt ↔ invoice, GR/IR clearing). Receiving = separate document. COA = QuickBooks default seed. **Strategic goal: replace QuickBooks.**
- **2026-06-02** — Vision sharpened: *run the whole company by conversation alone*. QB is the competitor (we are easier, lighter, no expertise required, plus strong inventory/assets/SCM). Approvals = **org-chart-based routing**. No reuse of existing code, no data migration (clean slate).
- **2026-06-02** — AI training strategy settled (§8.1): **facts via RAG/tools, behavior only via periodic LoRA**. No daily fine-tuning. Eval harness mandatory. Privacy solved by being fully local.
- **2026-06-02** — HR/org-chart module included (employees + reports_to, foundation for approval lines). Inventory depth = simple in/out + moving average + model name/serial # tracking (no multi-warehouse, BOM, or production). AI autonomy (§8.2) = auto posting + asking back when uncertain + weekly/monthly human audit.
- **2026-06-02** — USD single currency. Approvals = org chart by default + admin exception config. Financial statements/reports (BS/IS/CF/TB/GL/AP aging/inventory valuation) derived from journal entries + **callable via AI conversation**. **Accounting periods (close)** included → closing locks that period's entries.
- **2026-06-02** — **Business model disclosed:** a **commercial product** sold bundled with our own server hardware. Each customer gets a **single-tenant local appliance** (data never leaves = the selling point). Always starts from zero (no migration, permanently), per-customer setup (org chart, COA, posting rules) matters. No SaaS multi-tenancy.
- **2026-06-02** — Gap decisions: G1 (AR/sales) in Phase 1, G2 (bank reconciliation) = monthly statement upload → AI description matching, G3 (expense reimbursement) in Phase 1, G4 (opening balances) unnecessary (zero start).
- **2026-06-02** — Migration re-evaluated: zero start for our own use, but **migrating existing customers is a mandatory product feature for commercial sales** (onboarding milestone). AI parses QB exports and maps accounts → migration is also a differentiator.
- **2026-06-02** — Bank live feeds = future extension via a module adapter (add Plaid etc. as a bank-module adapter → everything else unchanged, per-customer on/off).
- **2026-06-02** — The inbound document classification pipeline (§8.4) is the premise of the retrieval gate = a core axis. Classification = security (sensitivity ACL) + automation (routing), dual purpose. Default-Deny (most restrictive level when uncertain). Added documents/document_categories/document_chunks. → Permission model corrected (§8.5): simple hierarchy → **3 axes (scope×level×data_boundary)**. Even within one department, staff/manager/director diverge by level and boundary (e.g., salary = (hr,3)). Axis (3) reuses the reports_to tree. Lightweight implementation: a user_scopes table + one decision formula.
- **2026-06-02** — AI permission & data access model settled (§8.3): **the LLM is not a security boundary**; permission checks are deterministic in code below the model. Triple defense = identity inheritance + tool gate (Forbidden) + **retrieval gate (RAG ACL-filtered at retrieval time → unauthorized data is absent from context)**. "Filter before retrieval." Prompt guardrails secondary only.
- **2026-06-02** — Mobile/tablet access clarified: "local" = data processed inside the box (no cloud transit), not a device-count limit. Phones/tablets = browser clients. External access via VPN. **Responsive + PWA makes a native app unnecessary**. HTTPS + 2FA for remote.
- **2026-06-02** — Group C policies closed → [docs/POLICIES.md]: G9 reversal-only + closed-period lock, G10 gapless numbering (PREFIX-YYYY-NNNN), G11 4-role permission matrix (employee/manager/accountant/admin; expense requesters get no GL; AI inherits caller permissions), G12 in-app + SSE notifications, G13 nightly backup + one-click restore.
- **2026-06-02** — Live bank feed decision: live feeds require **aggregators (Plaid/Yodlee/MX) = cloud**, conflicting with the "fully local, no data egress" selling point. → Default = **statement upload + AI parsing (bank-agnostic, local)**, plus OFX/QFX/CSV file support; Plaid only as an optional cloud add-on (explicitly surrendering locality).
- **2026-06-02** — Posting rules = **configurable table** (admin can change account mappings). Confirmed.
- **2026-06-02** — Module architecture confirmed → [docs/ARCHITECTURE.md]. Modular monolith (single process, strict separation). A module's sole entry point = service.py. Integration = synchronous calls (command/query) + domain events (reaction). Accounting connects only via event subscription + the posting rules table, decoupled (synchronous dispatch in the same transaction). AI tools = thin wrappers over services → human UI and AI share the same API.
- **2026-06-02** — Receiving auto-branches per line into asset vs. sale stock via product.type. Added **bidirectional inventory ↔ asset reclassification**: inventory → asset (moving-average cost), asset → inventory (net book value, NBV), serial numbers carried over, automatic journal entries. Added an Outbound document (sale/consumption/disposal/transfer, per-type journal entries).
