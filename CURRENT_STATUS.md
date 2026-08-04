# Current Status

> What works **today**, verified by the test suite and live use.
> Last updated: **2026-08-04** · 404 tests · 68 AI tools · 22 modules

## Verified end-to-end flows

**Procure-to-pay (chat-first).** Vendor onboarding with document attachment
(W-9) → purchase request by SKU or pasted product link (page fetched locally;
extracted price flagged for the approver) → org-chart approval in conversation
(approve / reject-with-reason) → PO issuance with vendor xlsx → PO-validated
receiving (over-receipts rejected; costs anchor to the PO) → true 3-way match
(an exception can never post) → payment with segregation of duties.

**Order-to-cash.** Quote → send → customer acceptance (PO) → shipment
(packing list, stock issue, COGS) → AR invoice (revenue) → receipt. Customer
documents (quote / packing list / invoice xlsx) download at each stage.
Write access is gated: pipeline moves need sales L2, invoicing needs finance L3.

**Autonomous fleet.** Uploaded documents are classified and parsed by a local
vision model, then drafted into work a human approves from one inbox
(`/fleet`): vendor invoices → draft bills (PO-matched when named), packing
lists → draft receipts, weekly payment runs, month-end close proposals,
anomaly alerts (spend spikes, duplicate bills), contract-renewal alerts, and
budget-overrun alerts. Drafts only — posting happens on human approval.

**Accounting core.** Double-entry ledger with event-driven posting rules,
moving-average inventory costing, straight-line depreciation, GR/IR clearing,
period close and locking, nine-sheet closing package, and the full report set
(BS / IS / CF / TB / GL / AP·AR aging / inventory valuation / cash runway).
QuickBooks Online import (`scripts/import_qbo`).

**Operations.** PTO with manager approval routed through the org chart
(balances derived from approved requests, never stored), new-hire onboarding
checklist (I-9, W-4, direct deposit), a contracts register with renewal
notice windows, and budget vs actual per expense account with actuals derived
from posted journals (unbudgeted spend listed explicitly).

**Email intake & outbox.** A mailbox is the fifth intake surface (chat,
uploads, bank files, schedules being the others): messages are parsed,
senders matched to vendor master data, invoices/packing lists dispatched as
fleet drafts, and statements/policy documents arriving by email are HELD for
a human — provenance default-deny. Outbound is maker-checker end to end: the
AI drafts, only a human sends, and the reference provider never leaves the
machine (`SENT_SIMULATED`; real IMAP/Gmail/Graph adapters are the private
deployment layer — see [docs/MAIL-INTEGRATION.md](docs/MAIL-INTEGRATION.md)).

**Policy-bounded autonomy (the L3 ladder).** Humans sign autonomy envelopes
(per-bill cap, daily velocity cap, vendor allowlist, budget headroom);
evaluation is pure code, unknown conditions fail closed, and no matching
envelope means today's approve-first behavior. Inside an envelope the fleet
posts through the same code path a human approval runs, leaves a post-hoc
review card, and repeated rejections suspend the envelope automatically.
Every evaluation writes an audit-shaped decision record.

**Compliance calendar.** Tax returns, annual reports, renewals, and labor
filings as one self-perpetuating calendar (completing a recurring duty
schedules the next occurrence), with an idempotent US reference seed
(federal + WA + Delaware) and weekly approaching-deadline cards.

**Payments: instructions, not transfers.** The system prepares the packet a
human needs to release money — payee, remit-to bank details, amount, wire
reference, and the evidence chain (PO, 3-way match, due date) — the human
executes the transfer at the bank, and only their confirmation (paid date +
bank reference) posts the payment journal. The system never claims to have
moved money, and the tools say so in their results.

## Agent architecture (implemented)

- **Plan-then-execute** — template plans for known intents (month-end close),
  gated LLM planning otherwise; live step checklist in chat
- **Live SSE streaming** — plan steps and tool calls appear the moment they run
- **Cross-conversation memory** — written only by audited tool calls
- **Governed learning loop** — rules mined from human resolutions, proposed in
  the approval inbox, active only after approval, application count measured
- **Execution timeline** — every tool call with status and latency under each reply
- **Honesty backstop** — a failed action can never be reported as a success
- **Deterministic model babysitting** (all battery-driven — [docs/EVAL.md](docs/EVAL.md)):
  today's date rides on the user turn (qwen ignored it in the system prompt and
  resolved bare dates to 2023), a foreign-script backstop regenerates replies
  that drift into Chinese or Russian, and a tool failing 3× in one turn is
  withdrawn so the model asks instead of retrying fabricated arguments
- **Runtime map** (`/map`) — the whole pipeline drawn live from the database

## Trust & security (implemented)

- 3-axis permissions (scope × level × data boundary) enforced identically for
  UI, AI tools, and RAG; re-checked at tool execution
- Maker-checker: AI-created money drafts require human confirmation in a
  separate turn before submission
- Prompt-injection defense: document content is treated as data, not instructions
- Authorization sweep test: every gated route returns an explicit 403 to an
  unauthorized user (21-route regression net)
- Deploy completeness: a fresh database installs from migrations alone —
  verified in CI against PostgreSQL 16 on every push
- Reversing entries only; gapless document numbering; full audit log

## Numbers

| Metric | Value |
|---|---|
| Automated tests | 404 (all passing; CI on every push) |
| Live-model battery ([docs/EVAL.md](docs/EVAL.md)) | 42/51 case-runs; all money-critical axes 3/3 |
| AI tools (audited, permission-gated) | 68 |
| Modules (vertical slices) | 22 |
| Architecture decision records | 11 ([docs/ADR.md](docs/ADR.md)) |
| Local models | qwen2.5:14b (chat) · qwen2.5vl:7b (vision) · bge-m3 (embeddings) |
| Cloud LLM calls | 0 |

## Known gaps (honest list)

- **Payroll and tax execution** — out of scope by design; the integration
  seam (org chart, GL, onboarding docs, compliance calendar) exists
- **Live bank feeds / payment rails** — statements import via CSV/OFX today;
  the system prepares payment instructions and records human-executed
  transfers; it never moves money (by design, not omission)
- **Real mailbox providers** — the MailProvider protocol and the full
  downstream pipeline are shipped and tested against the filesystem
  simulator; IMAP/Gmail/Graph adapters are private-layer work
  ([docs/MAIL-INTEGRATION.md](docs/MAIL-INTEGRATION.md))
- **Evaluation depth** — the live-model battery ([docs/EVAL.md](docs/EVAL.md))
  covers six behavior axes in two languages; broader paraphrase coverage and a
  versioned eval dataset are future work. Known 14B weak spots are documented
  there (runway/anomaly paraphrases, unknown-SKU evasion)
- **Approval-fatigue mitigation** — the inbox is chronological; risk-sorted
  ranking is designed but not built
- Dashboards beyond the runtime map; field-level close locking
