# Product Vision

> Traditional ERP asks humans to operate accounting software.
> 001 lets AI agents operate the business system — while humans keep approval
> and control.

## The problem, from someone who lived it

I ran the business side of companies for years — accounting, treasury,
procurement, HR, IT. The pattern is always the same: the software is a system
of record, and a human is the integration layer. A vendor invoice arrives by
email; a person reads it, retypes it, matches it to a PO, routes it for
approval, posts it, pays it, and files it. The ERP never did the work — it
just remembered what the human did.

LLMs change which side of that line the work sits on. Reading the invoice,
matching it, drafting the entry, noticing the duplicate — that is now machine
work. What must **stay** human is judgment: approving the spend, confirming
the amount, deciding the exception.

## What 001 is

An enterprise operating system designed AI-first around that split:

- **AI agents operate** — they read documents, execute tools, draft
  transactions, detect anomalies, and propose learned rules.
- **Humans govern** — every consequential action (posting, paying, sending,
  closing) passes a human approval point, and everything is audited.
- **The system enforces the split in code, not in prompts** — permission
  inheritance, maker-checker gates, draft-first autonomy, an honesty backstop.
  The LLM is treated as a talented but untrusted operator.

## Why fully local

The customers this serves (small and mid-size companies) are being asked to
send their books, payroll, and contracts to cloud AI vendors. 001 takes the
opposite bet: **a single-tenant appliance** — the application, the database,
and all three models (chat, vision, embeddings) run on hardware the customer
owns. "Local" means business data never feeds a cloud model — all inference
happens on the box — not device restriction: phones and laptops connect over
LAN/VPN. Your data trains nobody.

## Where this repository fits

This public repo is the **reference implementation** of the architecture: the
trust structures and the representative flows (procure-to-pay, order-to-cash,
autonomous fleet), working end to end on local models, with the test suite to
prove the invariants.

A real deployment adds a layer that is intentionally not here: installers and
appliance provisioning, customer data migration, live bank/payment/payroll
integrations, per-industry accounting rule packs, model-specific prompt and
evaluation assets, and operations tooling. That separation is the point — the
architecture is public and inspectable; the deployment layer is where a
product company differentiates.

## The endgame

Run the company through conversation. "We need two more GPU servers" becomes a
request, an approval, a PO, a receipt, a matched invoice, and a clean set of
books — with people touching it exactly where their judgment matters, and an
audit trail explaining everything the machine did in between.
