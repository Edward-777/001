# 001 — Global Policies (Group C, G9–G13) — Finalized

> Design-time document, kept because code comments cite its section numbers.
> For the implemented state see [CURRENT_STATUS.md](../CURRENT_STATUS.md).

Small rules that apply system-wide. Finalized with sensible defaults.

---

## G9. Posted Journal Correction Policy — reversing entries only (audit integrity)

- **Posted journal entries cannot be deleted or edited.** Corrections happen **only via reversing entries**.
  - Add `reverses_id` (original entry) / `reversed_by_id` (reversal) to `journal_entries`.
  - A reversal = a new entry with the original's debits/credits flipped, plus a corrected entry rewritten if needed.
- **No entry of any kind can enter a closed period** → adjusting entries go into a subsequent open period.
- Every change is recorded in `audit_logs` (who, when, what, rationale). **AI-created entries follow the same rules.**
- Draft-state entries can be freely edited or deleted (not yet on the books).

## G10. Document Numbering — per-type sequences, gapless

- Format: `PREFIX-YYYY-NNNN` (e.g. `PO-2026-0001`, `JE-2026-0042`, `EXP-2026-0007`).
- Counters are **per type, per year**, reset at year start.
- **Gapless (no missing numbers)** — an audit requirement. Numbers are **assigned inside the committing transaction** (roll back the transaction, the number rolls back too).
- Dedicated table `doc_sequences(doc_type, year, last_no)` + row lock guarantees concurrency safety.
- Prefixes: PO, INB (receiving), OUT (shipping), JE (journal), BILL (AP), PAY (payment), SO (sales order), INV (AR invoice), RCT (receipt), EXP (expense), RCL (reclassification), DEP (depreciation).

## G11. Permission Matrix — role-based + module-level

> Note on consistency: the four-role matrix below is a *summary* showing **each role's "default scope bundle"**. **The authoritative permission model is the three axes of DESIGN §8.5 (scope × level × data_boundary)**. A linear four-role model alone cannot express "does an accountant see HR salaries?" (finance ≠ HR) → hence §8.5 is authoritative. This table is used as the per-role default at ship time.

The role (`users.role`) expands to four tiers: **employee / manager / accountant / admin.**

| Capability | employee | manager | accountant | admin |
|---|:--:|:--:|:--:|:--:|
| Own requests and expense claims, view own documents | Yes | Yes | Yes | Yes |
| Approve/reject requests routed to them | — | Yes | Yes | Yes |
| Inventory, procurement, asset operations (receiving/shipping, PO, etc.) | Partial | Yes | Yes | Yes |
| **View journals, ledgers, financial statements (GL)** | No | No | Yes | Yes |
| AP/AR, payments, receipts, bank reconciliation | No | No | Yes | Yes |
| Period closing / reversing entries | No | No | Yes | Yes |
| Users, roles, **posting rules, system settings** | No | No | No | Yes |

- Key point: **an expense requester (employee) cannot see the GL or financial statements.** Accounting visibility starts at accountant.
- **AI tools also inherit the caller's permissions** — asking the AI to do something the user can't do still fails.

## G12. Notifications — in-app notification center + SSE real-time (email optional)

- Since everything is fully local, **in-app notifications are the default**. `notifications` table + **real-time push via SSE**.
- Triggers: approval arrival/approved/rejected, status changes on one's own requests, AI follow-up questions (uncertainty gating), bank reconciliation needed, AP/AR due dates approaching.
- Email/Slack are **optional adapters** (when the customer configures SMTP) — off by default.

## G13. Backup / Recovery — automatic appliance backups

- **DB**: nightly automatic `pg_dump` via APScheduler → local disk (+ a separate disk/NAS when available).
- **Attachments**: `uploads/` (original invoices, receipts, statements) backed up in sync.
- **Retention**: rolling 7 daily / 4 weekly / 12 monthly.
- **Recovery**: pick a backup on the admin screen → one-click restore (DB + files together).
- **Integrity**: automatic verification after backup (restore test or checksum).
- Single-tenancy means each appliance owns its own backups → customer data isolation comes for free.

---

## Summary of New/Changed Tables (from these policies)

- `journal_entries` += `reverses_id`, `reversed_by_id`
- `users.role` enum → **employee, manager, accountant, admin**
- New `doc_sequences(doc_type, year, last_no)`
- New `notifications(user_id, type, title, body, link, is_read, created_at)`
- New `audit_logs(actor_user_id, action, entity_type, entity_id, detail_json, at)` — shared by AI and humans
