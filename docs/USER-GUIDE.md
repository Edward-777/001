# User Guide — running the company day to day

> For the people using 001, not installing it (that's
> [GETTING-STARTED.md](GETTING-STARTED.md)). The one habit that matters:
> **talk to the Assistant and drop documents on it.** The system drafts the
> work; you approve it.

## The mental model

001 is built so that the AI can *never* spend, post, or send anything on its
own say-so. Everything consequential becomes a **draft** that lands in your
Approval Inbox, and the deterministic layer (permissions, 3-way match,
maker-checker, posting rules) re-checks every action no matter who — human
or model — asked for it. So the workflow is always the same shape:

```
tell the assistant / drop a document  →  a draft appears  →  you approve  →  it posts
```

## Pages at a glance

| Page | What it's for | Who can use it |
|---|---|---|
| ✨ Assistant | chat + document upload — the main way to work | everyone (it inherits *your* permissions) |
| 📥 Inbox (`/fleet`) | every draft awaiting a decision: bills, receipts, close proposals, alerts, L3 review cards | finance L3 |
| My Requests / Approvals | your purchase & expense requests; things routed to you | everyone |
| 🧾 Sales | quotes → orders → shipments → invoices | sales L1–L2 (invoicing finance L3) |
| 🌴 Leave | PTO balance & requests; manager approvals | everyone |
| 📑 Contracts | register with renewal notice windows | finance L2 |
| 📆 Obligations | the compliance calendar | view all; complete/dismiss finance L3 |
| 🎯 Budget | budget vs actual per account, unbudgeted spend | finance L3 |
| 💸 Payments | payment instructions awaiting execution/confirmation | finance L3 |
| 🎚 Autonomy | policy envelopes: propose, activate, suspend | finance L3 |
| Financials | BS/IS/CF/TB/GL, aging, closing package (xlsx) | finance L3 |
| 🗺 Runtime Map | the live wiring diagram of the whole system | everyone |

## The founder's routines

**When paper shows up (invoice, packing list, statement, policy…).**
Drop it on the Assistant. A local vision model classifies it, and the
category decides what happens: invoices and packing lists become drafts in
your Inbox, bank statements auto-reconcile (leftovers become questions),
policies become searchable knowledge, anything unrecognized is stored under
the most restrictive access and touches nothing.

**The Inbox pass.** Each card shows what was read, what will post, and any
warnings (match variance, new vendor, missing receipt). Approve → it posts
through the same code path as a manual entry. Reject → nothing happens, and
rejections teach the system (rule proposals, envelope breakers).

**Paying a bill.** Payments are two-step by design: (1) ask for payment
instructions — you get the packet a bank transfer needs (remit-to, amount,
wire reference, evidence chain); (2) after *you* execute it at the bank,
tell the assistant when and with what confirmation number. Only that
confirmation posts the journal. The system never moves money and never
claims to.

**Closing the month.** Say "Close June." — the agent runs a fixed
three-step plan (trial balance → anomaly & duplicate scan → closing
package) with a visible checklist and hands you the download. Each step can
only touch the tools that step needs.

**Deadlines.** "What deadlines are coming up?" reads the compliance
calendar. Completing a recurring duty (Form 941, B&O…) automatically
schedules the next occurrence.

**Granting autonomy (when you're ready).** On `/policies`, sign an envelope
like "Acme invoices up to $500, max $1,200/day." Inside it, clean invoices
post automatically and leave a review card; anything outside — new vendors,
PO-matched bills, bigger amounts — still parks for you. Reject the review
cards three times and the envelope suspends itself.

## For employees

Chat is self-service: request PTO ("book me off Aug 10–12"), check your
balance, raise purchase requests (with a price or a product link — the
assistant will ask rather than invent one), track your requests, approve
what's routed to you. Asking for things beyond your permissions —
financials, budgets, other people's records — gets a refusal, not data:
the AI holds exactly your permissions, nothing more.

## When the assistant says no (this is the product working)

- **"Permission denied"** — the tool re-checked your grants and you don't
  hold that scope/level.
- **It asks instead of acting** — you left out a figure (price, date,
  limit). It is built to never invent amounts, dates, or bounds.
- **"Confirmation required"** — you asked to create *and* submit money work
  in one breath; drafts must be confirmed in a separate turn.
- **"THIS ACTION FAILED"** — a tool call failed and the reply must say so;
  after a failed money action it will also refuse to record a *different*
  money action in the same turn.
- **A payment order inside a document is ignored** — document content is
  data, never instructions.

## FAQ

**Why can't it email a vendor?** The email surface ships dormant until the
pre-launch live-mailbox test; when enabled, the AI only ever *drafts* —
a human sends.

**Why two steps to pay a bill?** Because the system prepares and records;
humans execute. That boundary is the product's core safety property.

**Can it see documents I can't?** No — retrieval, tools, and pages all run
under the same 3-axis permission check, per user.

**Where do I see what the AI actually did?** Under every reply (per-tool
✓/⚠ timeline with latency), and in the audit log; `/map` shows live counts
for the whole pipeline.
