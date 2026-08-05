# Data Migration — bringing existing books into 001

> How a company that already has books (QuickBooks, Xero, Wave, FreshBooks, a
> spreadsheet, or an accountant's PDF pile) moves onto 001. The design is
> **source-agnostic**: 001 never needs to understand another product's export
> format — it needs a small set of universal facts every accounting system can
> produce. Source-specific adapters are deployment-layer work.

## The one decision that shapes everything: cutover, not replay

There are two ways to migrate books, and 001 picks the first:

1. **Opening-balance migration (the path).** Pick a cutover date — a fiscal
   year, quarter, or month start. Bring over *master data* and *the state of
   the company at that date*. History stays in the old system (kept read-only
   or exported to PDF and attached to 001's document store for search).
   This is how accountants actually move clients between systems: fast,
   verifiable, and the old system remains the audit trail for its own era.
2. **Full-history replay (not the path).** Re-posting years of journals
   requires reproducing the old system's posting semantics bug-for-bug.
   Enormous effort, near-zero decision value, and every discrepancy becomes
   an argument with the past. If a customer truly needs history inside 001,
   it is an adapter-level project, priced accordingly.

## What actually moves (the universal facts)

| Track | Facts | Lands as |
|---|---|---|
| Master data | Chart of accounts (or a mapping onto 001's built-in COA), vendors (terms, 1099 flag, remit-to), customers, products (SKU, cost), employees & org chart, active contracts, compliance duties | Plain rows — no journal impact |
| State at cutover | Trial balance | **One opening journal entry**, balanced or refused |
| | Open AR invoices / open AP bills | Open documents whose sum must tie to the AR/AP control lines of that trial balance |
| | Inventory on hand (qty × unit cost) | Stock records whose value must tie to the inventory line |
| | Fixed assets + accumulated depreciation | Asset register rows tying to the asset/contra lines |
| History | Old-system exports (PDF/xlsx) | Read-only attachments in the document store (searchable via RAG, never posted) |

## Three intake modes — all reuse surfaces 001 already has

**1. CSV templates (the universal, deterministic path).**
Seven files any system can export: `accounts.csv`, `vendors.csv`,
`customers.csv`, `products.csv`, `trial_balance.csv`, `open_invoices.csv`,
`open_bills.csv` (+ optional `assets.csv`, `contracts.csv`). Column specs are
dumb on purpose — name, number, amount, date. If a source can't produce one
of these, a spreadsheet and an intern can.

**2. Document dump (the AI-assisted path — 001's differentiator).**
The onboarding vision from the master design applies directly to migration:
drop the *documents* — last trial balance, AR/AP aging reports, a vendor
list, open invoice PDFs — and the same governed pipeline that handles daily
intake (classify → extract → **draft card** → human approves) turns them into
migration entries. Extraction is never trusted: every extracted row is a
draft a human confirms in the approval inbox, exactly like a vendor invoice
today. This is the mode for companies whose "system" is their accountant.

**3. Source adapters (deployment layer).**
A `MigrationSource` protocol mirroring `MailProvider`: an adapter's only job
is to emit the universal facts above from a source's API or export bundle
(QuickBooks, Xero, …). The public repo defines the contract; per-source
adapters live in the private deployment layer alongside the mail and bank
connectors.

## Validation gates (nothing posts until all of them pass)

Migration runs as **one batch with a dry-run report** — the same
fail-closed posture as the rest of the system:

- The trial balance must balance. If not, nothing imports.
- Open AR + open AP must tie to their control-account lines; inventory value
  must tie to the inventory line; assets to the asset lines. Every tie-out is
  reported with the exact difference.
- Duplicate detection runs before insert (the vendor-alias learning loop
  already knows how "Office Depot" and "Office Depot, Inc." collide).
- The report lists everything that will happen; the human approves the batch;
  only then does the opening JE post — through the same posting code and
  maker-checker gate as everything else, stamped with a migration batch id.
- Redo is a first-class case: the opening JE reverses cleanly (reversing
  entries only, as everywhere), master data upserts are idempotent on
  natural keys, and the batch id makes a re-run auditable.

## First-day-after checklist

- Bank statement import (CSV/OFX) from cutover date forward reconciles
  against the opening cash lines.
- The first month-close on 001 is the real acceptance test: TB, subledger
  tie-outs, and the closing package all derive from the migrated opening
  state plus new activity — discrepancies surface immediately, while the old
  system is still warm.
