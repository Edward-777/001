# 001 — Enterprise AI Operating System · Master Summary (one page)

> The full picture of project **001**'s design. Details live in six documents. (Updated 2026-06-05 — reflects D6 autonomous fleet, O2C, and code review.)
> [DESIGN.md](DESIGN.md) · [docs/SCHEMA.md](docs/SCHEMA.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/POLICIES.md](docs/POLICIES.md) · [docs/AI-AGENT.md](docs/AI-AGENT.md)

---

## One sentence
**An Enterprise AI Operating System where AI agents run company operations and humans only approve.** Fully local (both data and AI stay inside the customer's box), a single-tenant appliance bundled with our own server hardware. Finance, procurement, inventory, and sales are the current scope, expanding to IT, HR, and the rest of operations.

## Vision / Business
- **Endgame:** Run the entire company through conversation alone. ("Go on a business trip" → the AI handles the request, approvals, and journal entries.)
- **Business model:** Commercial product, bundled with the server. Each customer gets their own box (no data leaves the premises = the **selling point**). SaaS multi-tenancy: No.
- **Fully local:** Both data and AI stay inside the customer's box. "Local" means no data egress, not device restriction — phones and tablets connect via LAN/VPN browser (PWA, no native app needed).

## Platform / Stack
- 30 concurrent users · 1 host machine (GPU) + browser · internal network + VPN (WireGuard) · HTTPS / remote 2FA
- **Python · FastAPI · PostgreSQL · SQLAlchemy · HTMX/Jinja2/Tailwind · session auth · APScheduler · Ollama · pgvector**
- No Redis, Celery, Nginx, Docker, reuse of existing code, or data migration (personal use).

## Business Domains (Phase 1 = full accounting cycle)
```
Request → [org-chart-based approval] → Purchase (PO) → Receiving (separate document) → Inventory (moving average) ⇄ Assets (straight-line depreciation)
                                                    └ model name / serial # tracking
        + Sales/AR (customers, sales orders, invoices, receipts)  + Expense reimbursement (Non-PO, employee refunds)  + Bank reconciliation (monthly statement upload + AI)
        → automatic double-entry journal at every step → accounting periods (closing) → financial statements (BS/IS/CF/TB/AP·AR aging)
```
- **Accounting:** US GAAP · USD · sales tax · standard US COA. AP = **3-way match** (PO ↔ receiving ↔ invoice, GR/IR clearing).
- **HR / org chart:** employees + `reports_to` → foundation for approval chains and permission boundaries.
- **Bidirectional inventory ↔ asset conversion** (reclassification, book-value journal entries).

## Architecture
- **Modular monolith** (single process, strict separation). Modules: core · auth · hr · approval · procurement · inventory · assets · sales · expense · bank · accounting · documents · ai.
- **A module's sole entry point = `service.py`** (human UI, AI tools, and other modules all call the same functions).
- **Integration:** need something = synchronous call / reacting to something = domain event. **Accounting is connected only via event subscription + a configurable posting rule table** (GL account knowledge lives in accounting alone). Events dispatch synchronously in the same transaction → consistency + lightweight.

## AI (governance §8 + mechanics in AI-AGENT.md)
- **Tool-first:** the AI = "a user who presses buttons with words". Tools = thin wrappers over service (schemas auto-generated).
- **Learning:** facts = RAG / live DB (zero training), behavior = periodic LoRA + eval. No daily fine-tuning. **The asset = the dataset** (the model is a replaceable substrate).
- **Autonomy:** automatic posting + ask back when uncertain + weekly/monthly human audits + full audit log for every action.
- **Security chain:** §8.6 input gateway (isolation, Default-Not-Indexed) → §8.4 inbound classification (tagging) → §8.5 three-axis permissions (judgment) → §8.3 retrieval gate (data without permission is absent from context). **The LLM is not a security boundary — deterministic controls in code.**
- **Three permission axes:** scope (hr/finance/inventory/system) × level (1–3) × data_boundary (self/team/dept/all, reusing reports_to). Applied identically to UI, AI, and RAG.
- **Models:** development = Qwen2.5 (4090). Shipping = both Llama 3.3 70B (US-made, safe default) and Qwen2.5-72B (performance) preinstalled; customer picks at install time. Scope = work-only by default + admin toggle for a general assistant.

## Global Policies (POLICIES)
Reversing entries only (no deletion) · period-close locking · gapless numbering (PREFIX-YYYY-NNNN) · four-role permission defaults (source of truth = §8.5) · in-app + SSE notifications · nightly backups + one-click restore.

## Roadmap
Phase 1 lightweight core (full cycle) → Phase 2 agent hookup → Phase 3 document parsing, classification, RAG queries → GTM onboarding/migration → Phase 4 in-house fine-tuning.

## Current Implementation Status (Phase 1–3 + D6 core + chat P2P + agent architecture)
- **Phase 1–3 done:** full accounting cycle (manual/UI) + local Ollama agent (tools = service, permission inheritance) + RAG (company policies) + vision invoice parsing. **294 tests · 44 AI tools.**
- **Chat P2P complete:** vendor onboarding (W-9 attachment) → purchase request (price extracted from a product **link**, approver double-check) → org-chart approval (approve / reject-with-reason in conversation) → PO issuance + vendor xlsx → PO-validated receiving (over-receipt rejected, PO unit price as anchor) → **true 3-way match** (exceptions not posted) → payment (segregation of duties, L2/L3).
- **Agent architecture:** **plan-then-execute** (month-end close template plan + gated LLM planning, rendered as a checklist) · **cross-conversation memory** (written only via audited tools) · **governance learning loop** (mine rules from human judgments → propose in approval inbox → activate → measure applied_count, ADR-10) · execution timeline (tools, status, latency) · honesty backstop (cannot report a failure as a success). Design rationale = [docs/ADR.md](docs/ADR.md).
- **D6 autonomous agent fleet (`fleet` module):** intake (uploads, conversations) → dispatcher → a **single work loop** processes per role (drafts) → human approval in the **approval inbox `/fleet`** → posting. Roles: Spend/AP (incl. 3-way PO matching) · Supply (packing list → receiving draft) · Revenue/Collections · Accounting (weekly payment run, month-end close) · Treasury/Insights (runway, anomaly detection, **learned rule proposals**). All of it is **draft-first; consequential actions are gated behind human approval**.
- **Order-to-cash (O2C) `/sales`:** quote → send → customer PO intake → shipment (packing list, inventory deduction) → invoice (revenue recognition). Each step offers **customer document downloads (quote, packing list, invoice xlsx)**.
- **Security (two models):** (1) **Interactive** (UI, AI) = runs as the calling user, inheriting scope × level × boundary gates. (2) **Autonomous fleet** = system actor; instead of permission gates, the **approval inbox is the single control point** (finance L3). Both: zero company data leaves the box (local LLM); only public, abstracted information goes outside (escalation: local → web search → frontier model for methodology advice). Details = [docs/AGENT-FLEET.md](docs/AGENT-FLEET.md).
- Modules: core · auth · hr · approval · procurement · inventory · assets · sales · expense · bank · accounting · documents · ai · **fleet**.

## Open Items (minor)
- Benchmark the shipping model default (Llama 70B vs Qwen 72B); peak concurrent AI users → Ollama/vLLM
- Group B follow-ups (returns, physical inventory counts, payroll, budgeting) — phase not yet decided
- Field-level close locking (and some state-transition coverage)
