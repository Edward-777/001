# 001 — Autonomous Operations Agent Fleet Design (D6, v2)

> Endgame: **beyond "run the company through conversation" — "a company that runs itself even without conversation."**
> Role-based AIs handle the day-to-day work; the human (founder) only sets direction, handles exceptions, and approves.
> Living document — refined continuously as we implement stage by stage.

## Target = generic small startup (product for sale)

- **001 is a product we're building to sell.** It is modeled not on any specific company but on a **typical small startup (1–30 people)**.
  *(The imported QBO data is for development/testing only — it is not the target customer profile.)*
- The founder alone, or a handful of people, wears every hat — there is no purchasing department or finance department.
- They want to run the company **without accounting knowledge** — the key differentiator vs. QuickBooks.
- Industries vary (SaaS, agency, e-commerce, small hardware) → **no industry assumptions; modular.**
- **Lightweight is the essence of the product** — never force a heavyweight nine-department structure.

### Differentiator: "the accounting is invisible"
> With QuickBooks, the founder *does the accounting.* With 001, **you only deal with money coming in and going out, and the books write themselves**; the founder just converses and approves. Accounting is a byproduct, not a chore.

---

## 0. Core philosophy

- **Logic = hands/calculator (accuracy)** · **AI = brain/interpreter (understanding and judgment)**.
- **The AI never invents numbers.** Every figure comes only from values the tools pull out of the ledger (hallucination guardrail).
- **For high-consequence actions (money, outbound sends, hiring), the AI only prepares; the final click is human.**
- **Permissions define the boundary of a role.** Each role executes as a bundle of permissions → the tools enforce permissions automatically.

---

## 1. The full map of running the company (value flows)

A small startup runs not on departments but on **3 flows + automatic books + insights**:
```
Money in (sales -> collections)   --+
Money out (spend -> payments)     --+-> Books happen "automatically" -> Cash, runway, insights -> Founder
People (payroll, optional)        --+       (accounting is a byproduct)    "How much money is left?" "Can we afford this?"
```
Accounting (record-keeping) is not the engine of the company but the **downstream where all flows converge**. The engine is earning money, spending money, and people.

---

## 2. Role lineup — 5 core + 4 optional (all built into the product)

| Role | Flow | Mapped modules | Core responsibilities | Default |
|----|------|---------|---------|------|
| Chief of Staff (Dispatcher) | All | ai/classify | Classify and route inbound items, handle bounces and escalations + conversation interface with the founder | Core |
| Revenue / AR | Money in | sales | Customer invoices, collection reminders, revenue recognition | Core |
| Spend / AP | Money out | procurement/expense, accounting(ap) | Bills, receipts, subscriptions, vendor payments | Core |
| Accounting / Tax | Records | accounting | **Auto-posting** from the flows above + close, tax, reporting | Core |
| Treasury / Insights | Founder layer | accounting/bank | Cash, burn rate, runway, "can we afford it?", anomaly alerts | Core |
| People / Payroll | People | hr, expense | Payroll, contractors, onboarding, expense policy | Optional |
| Inventory / Purchasing | Supply | inventory, procurement | Inventory, POs, receiving, 3-way match | Core (packing list -> receiving draft) |
| Documents / Legal | Horizontal | documents, ai/rag | Store/search contracts and policies | Optional |
| Customer | Horizontal | sales | Inquiries, renewals, customer-reply drafts | Optional |
| Founder (CEO) | — | Human | Direction, approve/reject, questions | Human |

**Treasury / Insights is the hidden star** — the thing a startup most wants to know, "How much runway? When do we run out of money?", is something QuickBooks shows poorly. It is our differentiating weapon.

### Revenue / AR input sources (staged)
| Input | Method | Stage |
|------|------|------|
| Chat — invoicing | "Bill ACME $5k for consulting" -> draft invoice | Stage 2 |
| Chat — deposits | **"$5k came in from ACME"** -> record deposit -> offset against open invoices | Stage 2 |
| Customer documents | Upload customer PO / quote / SOW -> draft invoice | Stage 2 |
| Recurring billing | Set up a subscription once -> auto-generate a monthly invoice (SaaS) | Stage 2 scheduled |
| **Month-end bank matching** | Auto-reconcile statement deposits against open invoices -> confirm collections | Reuses existing reconciliation |
| Integrations (Stripe, Shopify) | Auto-collect revenue (data-source API = IN, safe) | Optional, later |

- **Collections (AR):** automatically track open invoices -> **draft** reminder emails (sending is gated).

### Treasury / Insights metrics (finalized)
**Always-on dashboard:** cash balance · burn rate (net monthly outflow) · **runway** (cash / burn rate — the hero metric) ·
revenue trend (MRR after subscription tagging) · receivables / payables.
**Proactive push:** anomaly alerts (spend spikes, duplicate payments, forgotten subscriptions) · "can we afford it?" (instant answer with runway impact).
> Most of this is computable immediately from current data; only MRR and the anomaly-detection baseline need a little extra work.

### Availability model — everything always available (no activation concept)
- **Every role is always listening.** There is no on/off event — because idle cost is ~0:
  ```
  Single loop wakes -> anything in the queue? (DB query, zero GPU) -> nothing? go right back to sleep
  Only when there is work -> put on that task's to_role and call the LLM (GPU used)
  ```
  In other words, **"the loop is running" != "the GPU is being used."** GPU only when there is actual work to process.
- **An "optional" role isn't switched off — it's a role that only works when its kind of work arrives.** A SaaS startup never gets inventory work, so the inventory role simply stays quiet forever — self-regulating with no separate activation or notification procedure.
- **The only user setting = "permanently off" (deliberate exclusion).** Example: payroll handled externally via Gusto -> turn off the People / Payroll role.
- **The real safety net is downstream:** whichever role does the processing, drafts, postings, and payments all go through the founder approval gate.

---

## 3. Orchestration — single work loop + task queue

**Not nine loops, one per department — one loop that works the task queue**, swapping roles as it goes:
```
Inbound (email / upload / statement / chat instruction) -> [Dispatcher] classify -> enqueue into tasks (to_role + content + pending)
[Work loop] pull next task from queue -> put on the to_role's "prompt + tools + permissions" and process
   -> handle it  /  bounce back with "not mine + reason"  /  high-consequence items -> 'needs approval' -> founder
   -> bounced 3+ times -> escalate to founder
```
- **The real limit = 1 GPU = 1 concurrent LLM call.** When work piles up it is processed sequentially — irrelevant at startup scale.
  (Later scaling is solved not by turning off the loop but with a faster GPU / parallelization.)
- **Scheduler = APScheduler (in-process).** Runs inside the FastAPI app. No external dependencies.
- **Every action = audit log** (already implemented).

### Task queue table `tasks`
| Field | Type | Description |
|------|------|------|
| id | PK | |
| created_at / updated_at | datetime | |
| source | enum | upload·email·bank_feed·ceo_chat·agent |
| source_ref | str? | document_id / email_id / conversation_id |
| category | str | Dispatcher classification result |
| from_role | enum | dispatcher·revenue·spend·accounting·insight·people·supply·docs·support·ceo·system |
| to_role | enum | Assigned owner role (same enum as above) |
| title | str | Human-readable one-line summary |
| payload | JSON | Task data (parsed invoice, instruction text, etc.) |
| status | enum | queued·in_progress·needs_approval·bounced·done·failed |
| bounce_count | int | Bounce count (default 0) |
| bounce_reason | str? | Reason for the last bounce |
| result | JSON? | Output (draft invoice id, draft email id, ...) |
| approval_id | FK? | Link to the existing approval module when needs_approval |
| idempotency_key | str? unique | hash(source_ref+category) — prevents duplicate creation on loop reruns |

**State transitions:**
```
queued -(work loop picks it up)-> in_progress
in_progress -> done
            -> needs_approval -(founder OK)-> done   -(rejected)-> failed
            -> bounced -(dispatcher reassigns)-> queued  (bounce_count++)
            -> failed
bounce_count >= 3 -> needs_approval  (escalate to founder)
```
- **Dedup:** `idempotency_key` unique + status filter -> even if the periodic loop runs again, already-handled items are not picked up.
- **Bounce:** misassigned items go back to the dispatcher with a reason -> reclassify. Reasons are logged to improve classification.

### Dispatcher classification -> role mapping
| category | -> Owner role | First action | Status |
|----------|----------|---------|------|
| invoice (vendor bill) | Spend / AP | Parse -> draft bill (hold if goods not yet received) | Done — current classifier |
| bank_statement | Accounting | Auto-reconciliation proposal | Done |
| receipt (receipt / expense) | Spend / AP | Draft expense entry | Done |
| policy (policy question) | Documents / Legal | RAG answer | Done |
| contract | Documents / Legal | Summarize, classify, archive | Done |
| customer_invoice / order | Revenue / AR | Draft customer invoice | Planned — classifier extension |
| po_request | Inventory / Purchasing | Draft PO | Planned — extension (approved request -> PO is automatic via event; issue via chat issue_po) |
| goods_receipt / packing_list | Inventory / Purchasing | Receiving draft -> on approval, post + PO rollup -> 3-way match | Done — shipped |
| hr_doc | People / Payroll | Organize employee records | Planned — extension |
| customer_email | Customer | Draft reply | Planned — extension |
| other / ambiguous | Dispatcher holds | Escalate to founder when ambiguous | Done |

> The current classifier (`classify.py`) recognizes only 6 document types. **The 5 "Done" types are enough for Stage 1**;
> the "Planned" extensions are added stage by stage as the classifier grows.

### Inbound channels
Source-agnostic — to the dispatcher everything is just "one item to process": email · upload · bank statement · chat instruction.

---

## 4. Loop cadence — producers (schedules) + consumer (single loop)

The work loop (consumer) is always on. Below are the **scheduled producers that enqueue work**:
| Cadence | Trigger |
|------|--------|
| 10 min | Reactive: process new email, documents, conversations |
| Daily | Clear leftovers, asset checks (optional roles) |
| Weekly | Spend / AP builds the payment list -> founder, weekly summary |
| Monthly | Close (closing package), verify prior-month reconciliation |

### Weekly payment flow (payment run)
```
[Weekly] Collect unpaid bills into "this week's payment list" -> founder
[Founder] Wires the money at the actual bank -> "done" (confirm per item)
[Accounting] Final journal entry (Dr Accounts Payable / Cr Cash)
[Bank statement arrives] Verified via auto-reconciliation <- the books audit themselves
```

---

## 5. Automation vs. human approval boundary

| AI end-to-end (automatic) | Human approval required |
|------------------------|--------------|
| Classify, route, organize, draft | **Every actual payment (regardless of amount)** |
| Invoice and expense **drafts** | Outbound email / contract sends |
| Bank reconciliation **proposals** / ledger posting **drafts** | Executing ledger postings |
| Reports, Q&A, insights | Hiring/firing · irreversible or high-value decisions |

> **Drafts only; execution is human.** Even when no money moves, a ledger posting is a high-consequence action -> conservative at first.
> As trust builds, low-risk auto-posting can be relaxed in.

---

## 6. Security model — "our data never leaves"

### Two principles
1. **Company data never goes outside** (numbers, names, contracts — not a single byte).
2. **When we don't know something, we only bring "knowledge" in from outside** — what goes out is a "how-to / factual question," never company data.

### Two kinds of API — direction is everything
| Kind | Direction | Risk |
|------|------|------|
| Cloud AI APIs (OpenAI/Gemini/Claude) | My data goes OUT | Red — the real risk. 001 **does not use them** (local LLM) |
| Data-source APIs (Gmail/bank/QBO) | My data comes IN | Green — safe. Downloaded locally, analyzed locally |

- **"Local LLM" is not broken by connecting email or banking** (analysis is local; the LLM never touches the internet).
- **"API vs. browser" is a meaningless distinction** — what matters is "what data goes out." Pasting company material into ChatGPT via a browser = the same leak as an API. The browser's safe use = public information IN (web search, tax rates).

### Escalation when we hit something we don't know
```
1. Local first    -> tools, company policy (RAG)
2. Web search     -> public facts (only the search query goes out)
3. Frontier consult -> "methods" only (zero data, human-reviewed before sending)
e.g. OK: "AP subledger is 0 but the GL control account shows a large balance — likely causes and reconciliation approach?"
     NOT OK: "Why doesn't our company's AP balance?"
```

### Enforcement — prompt rules + technical fences
1. **Structural isolation** — the parts that touch company data have zero internet. The only outbound path is a single narrow "external query" channel.
2. **Egress guard** — if outbound text contains company data, block/mask it.
   Detection = **DB name lists (vendors, customers, employees, account names) + patterns (amounts, account numbers, EIN, email addresses).**
3. **Human approval** — external questions are drafts only -> a human reviews and sends.

### Email connector (the only door to the outside)
```
[Internet] --TLS--> [Email connector] <- the only external path (read-only, audit-logged)
                        v
[LLM / engine / DB] <- fully offline
```
- Standard setup = **Google Workspace** -> **Gmail API + OAuth read-only** (drafts are saved via the API too).
- Even with cloud email, analysis is local — we are pulling our own mail down locally, which is a security win.
- Tokens stored encrypted. **Sending is never automatic — drafts only.** Email bodies = untrusted (injection defense).

---

## 7. Hybrid intelligence — relieving the pressure to keep local models current

- **Local:** everyday execution (data processing). **Frontier on-demand:** methodology consulting for hard problems (zero data).
- **Local model updates are free and easy** — we are freed from the "pressure" of chasing the frontier, not frozen forever.
- The frontier model = a **consultant** who never sees the books (methods). Local + engine = the **practitioner** (executes on real data).

---

## 8. Rollout approach (staged — core first, not everything at once)

- **Stage 1:** Dispatcher + Spend / AP — **2 roles.** Validate the single work loop + tasks queue + draft/approval flow.
  Inputs = (a) uploaded documents inbox + (b) chat instructions (no email, no bounces).
- **Stage 2:** Bounces and escalation + Revenue / AR + Treasury / Insights join (core complete).
- **Stage 3:** Email connector + weekly payment loop (external I/O appears).
- **Stage 4:** Optional roles (people, supply, docs, support) auto-activate + classifier extensions + automated month-end close.

---

## 9. Stage 1 implementation spec (Spend / AP loop)

**Principle: drafts only. Ledger posting happens only after founder approval.**
```
[Work loop] picks up a queued Spend/AP task -> in_progress
  1. Parse the invoice (vendor, amount, line items)                 <- automatic
  2. Look up the vendor. If missing, attach a "new vendor proposal" <- automatic
  3. Goods received? Goods before receiving -> hold + notify / services -> recommend account <- automatic
  4. Create the draft bill (all fields filled)                      <- automatic
  5. status=needs_approval -> founder                               <- stop
[Founder] approves -> 6. Actual posting + (if new) auto-create the vendor
```
- **Vendor master auto-fill:** for unregistered vendors, the draft carries a "register new vendor" attachment that is created together on approval.
- **Automatic OK:** parsing, classification, vendor lookup, account recommendation, drafts, reconciliation proposals. **Gated:** postings, payments, outbound sends.

### payload JSON (per category)
```jsonc
// invoice
{ "document_id": 42, "goods_received": false,
  "parsed": { "vendor_name": "ACME Cloud Inc", "invoice_no": "...", "date": "2026-05-01",
              "currency": "USD", "lines": [{"description":"...","qty":1,"unit_price":1200.00}],
              "subtotal": 1200.00, "tax": 0, "total": 1200.00 } }
// bank_statement
{ "document_id": 51, "bank": "...", "period": "2026-05",
  "lines": [{"date":"...","description":"...","amount":-1234.56}] }
// ceo_chat
{ "conversation_id": 19, "instruction": "Process this invoice", "refers_to_task_id": 7 }
```

### Classifier extension timeline
- **Stage 1:** current 6 types (invoice, bank_statement, receipt, policy, contract, other).
- **Stage 2:** +`customer_invoice` (revenue role).
- **Stage 3:** +`customer_email`. **Stage 4:** +`po_request`, `goods_receipt`, `hr_doc` (optional roles).

---

## 10. Decision log / open questions

**Decided (D6):**
- [x] Target = generic small startup (product for sale); imported data is test-only
- [x] Roles = 5 core + 4 optional, **all always available** (no activation concept; "optional" = works only when relevant work arrives), permanent-off option
- [x] Implementation = **a single work loop** that swaps roles as it processes (not 9 processes)
- [x] Company email = Google Workspace -> Gmail API read-only
- [x] Payments / postings = **drafts only, execution requires founder approval** (regardless of amount)
- [x] Scheduler = APScheduler · egress guard = DB name lists + patterns
- [x] tasks schema + state transitions + 3-bounce escalation + idempotency
- [x] Dispatcher mapping · payload formats · classifier extension timeline

- [x] Revenue / AR inputs = chat (invoicing/deposits), customer documents, recurring billing, **month-end bank matching**, integrations (later) (see section 2)
- [x] Treasury / Insights metrics = cash, burn rate, **runway**, revenue trend, receivables/payables + anomaly alerts and "can we afford it?" (see section 2)
- [x] ~~UI notification for optional-role auto-activation~~ -> **dropped.** All roles are always available, so there is no activation event.

> **Design detail 100% complete.** Every decision is locked in. All that remains is implementation.

---

## 11. Implementation status

Module: `app/modules/fleet/` (models·service·dispatcher·roles·loop·payment_run) +
`app/web/fleet_routes.py` (approval inbox). Everything ships with tests.

| Milestone | Content | Status |
|---------|------|------|
| 1 | `tasks` queue model + state-machine service (idempotency, bounce, escalation) | Done |
| 2 | Dispatcher (category -> role routing) | Done |
| 3 | Spend / AP role handler + single work loop (draft -> approval -> posting) | Done |
| 4 | Approval inbox UI + upload -> dispatcher wiring + APScheduler tick | Done |
| 5 | Treasury / Insights (runway, burn rate, affordability) + AI tools | Done |
| 6 | Revenue / AR role (customer invoice draft -> approval -> revenue recognition) | Done |
| 7 | Weekly payment list (payment run) -> payment journal entry on approval | Done |
| 8 | Anomaly detection (spend spikes, duplicate bills) + daily inbox alerts | Done |
| 9 | Month-end close proposal -> period lock on approval | Done |
| 10 | Insights dashboard cards (runway, burn rate, cash) + inbox counts | Done |

Scheduler jobs: work loop (10 min) · weekly payment run (Mon 08:00) · anomaly detection (daily 07:00) ·
month-end close (1st, 06:00) · nightly backup.

**Remaining work (follow-ups):**
- Email connector (Gmail API OAuth) — **requires the user's Google Workspace credentials** (external dependency)
- Optional role handlers (people, supply, docs, support) — after extending the classifier beyond the current 6 types (requires LLM classification training)

> **Design v2 complete.** Realigned around the generic small startup. Next up is Stage 1 implementation
> (tasks table + APScheduler + single work loop + Spend / AP draft flow).
