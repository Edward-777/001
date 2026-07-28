# 001 — Data Schema (D13)

> v0.1 draft. Field-level detail for the domain model in [DESIGN.md](../DESIGN.md) §5.
> Scope: **Phase 1 = Purchase → Inventory → Assets → Accounting + Sales/AR + Expense Reimbursement + Bank Reconciliation** (the full cycle).
> Notation: `PK`=primary key, `FK`=foreign key, `enum(...)`=fixed value set, money=USD `Numeric(15,2)`.
> Common columns (all tables): `id PK`, `created_at`, `updated_at`, `created_by FK→users`.

---

## A0. System-Wide (POLICIES)

### doc_sequences (gapless numbering — §G10)
| Column | Type | Notes |
|---|---|---|
| doc_type | text | PO, JE, EXP, INV... |
| year | int | per year |
| last_no | int | Last number issued. **Allocated under a row lock within the transaction** |

### notifications (in-app notifications — §G12)
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users | recipient |
| type | text | approval/rejection/ai_question/bank/due... |
| title / body | text | |
| link | text | navigation target on click |
| is_read | bool | |
| created_at | timestamp | pushed in real time via SSE |

### audit_logs (audit trail — shared by AI and humans, §G9 / autonomy)
| Column | Type | Notes |
|---|---|---|
| actor_user_id | FK→users | actor (AI actions are recorded too) |
| action | text | create/post/reverse/approve... |
| entity_type / entity_id | text/int | target |
| detail_json | jsonb | what changed, plus supporting documents |
| at | timestamp | |

## A. Master Data

### users
| Column | Type | Notes |
|---|---|---|
| name | text | |
| email | text unique | login ID |
| password_hash | text | bcrypt |
| role | enum(employee, manager, accountant, admin) | assigns the default scope bundle (POLICIES §G11) |
| department_id | FK→departments | nullable |
| is_active | bool | |
| → Actual permissions are refined via user_scopes (DESIGN §8.5 — three axes) |

### user_scopes (three permission axes — DESIGN §8.5)
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users | |
| scope | enum(hr, finance, inventory, procurement, system) | (1) domain |
| level | int (1~3) | (2) grade (e.g. hr 3 = salary data) |
| data_boundary | enum(self, team, department, all) | (3) data boundary (based on the reports_to tree) |
| → Check: user.level[scope] ≥ data.level AND the target falls within the boundary (reports_to subtree) |

### departments
| Column | Type | Notes |
|---|---|---|
| name | text | |
| parent_id | FK→departments | hierarchy (nullable) |
| manager_employee_id | FK→employees | department head (default approver candidate) |

### employees (HR / org chart — the foundation of approval routing)
| Column | Type | Notes |
|---|---|---|
| employee_no | text unique | |
| name | text | |
| department_id | FK→departments | home organization |
| position_title | text | job title |
| **reports_to_id** | FK→employees | **reporting line (superior)** — approval chains climb this chain |
| hire_date | date | |
| status | enum(active, on_leave, terminated) | |
| user_id | FK→users | linked login account (nullable; not every employee is a system user) |
| → When registering a new hire, set only department + reports_to and approval routing forms automatically from then on |

### vendors (suppliers)
| Column | Type | Notes |
|---|---|---|
| name | text | |
| tax_id | text | US EIN (for 1099) |
| is_1099 | bool | subject to year-end 1099 |
| email / phone / address | text | |
| payment_terms | enum(due_on_receipt, net15, net30, net60) | AP due-date calculation |
| is_active | bool | |

### products (items)
| Column | Type | Notes |
|---|---|---|
| sku | text unique | |
| name | text | |
| model_name | text | model name |
| type | enum(inventory, asset, consumable, service) | **the key branch point for auto journal entries** |
| track_serial | bool | if true, track individual units by serial |
| unit | text | ea, box, hr... |
| category_id | FK→product_categories | nullable |
| standard_cost | money | for reference |
| default_expense_account_id | FK→accounts | default account when expensed |
| is_active | bool | |

### inventory_serials (serial tracking — items with track_serial=true)
| Column | Type | Notes |
|---|---|---|
| product_id | FK→products | |
| serial_no | text | unique unit identifier |
| status | enum(in_stock, sold, scrapped) | |
| unit_cost | money | acquisition cost of the unit |
| inbound_line_id | FK→inbound_lines | receipt source |
| outbound_ref | text | on issue/sale |
| → Valuation stays at item-level moving average; serials only track "which units are in stock" |

### Lookup tables (classification settings referenced elsewhere — configuration-type)
| Table | Columns | Notes |
|---|---|---|
| **product_categories** | name, parent_id(nullable) | referenced by products.category_id |
| **expense_categories** | name, default_expense_account_id FK→accounts | referenced by expense_lines.category_id → maps to expense accounts via posting rules |
| **tax_codes** | name, rate(%), tax_account_id FK→accounts | referenced by ar_invoices.tax_code_id. Sales tax (per state/locality) |

### accounts (chart of accounts, QuickBooks-style COA)
| Column | Type | Notes |
|---|---|---|
| code | text unique | e.g. 1200 |
| name | text | e.g. Inventory Asset |
| type | enum(asset, liability, equity, revenue, expense) | |
| subtype | text | current_asset, fixed_asset, AP, COGS, expense... |
| parent_id | FK→accounts | hierarchy (nullable) |
| is_active | bool | |
| → A default COA is provided as seed data (standard set for US small business) |

---

## B. Workflow (Request → Approval)

### requests (requests / requisitions)
| Column | Type | Notes |
|---|---|---|
| request_no | text unique | auto-generated, REQ-2026-0001 |
| type | enum(purchase, expense, trip, general) | |
| requester_id | FK→users | |
| department_id | FK→departments | |
| title | text | |
| description | text | |
| total_amount | money | sum of lines |
| status | enum(draft, submitted, approved, rejected, canceled) | |
| submitted_at / decided_at | timestamp | nullable |

### request_lines
| Column | Type | Notes |
|---|---|---|
| request_id | FK→requests | |
| product_id | FK→products | nullable (free-text allowed) |
| description | text | |
| qty | numeric | |
| estimated_unit_price | money | |
| amount | money | qty × price |

### approval_lines (approval chain)
| Column | Type | Notes |
|---|---|---|
| request_id | FK→requests | |
| approver_id | FK→users | |
| step_no | int | approval order |
| status | enum(pending, approved, rejected, skipped) | |
| comment | text | |
| decided_at | timestamp | |

### approval_rules (approval rules — auto-build the approval chain)
| Column | Type | Notes |
|---|---|---|
| applies_to_type | enum(request type) | |
| min_amount / max_amount | money | amount band |
| routing | enum(org_chart, fixed_role, fixed_employee) | **routing method** |
| climb_levels | int | for org_chart: how many levels to climb reports_to (e.g. larger amounts climb higher) |
| fixed_role / fixed_employee_id | — | target when routing is fixed |
| → On submission: approval_lines are auto-generated by following the requester employee's reports_to chain plus the amount-band rules |
| → Default is **org-chart based** (climb the reporting line); higher amount bands climb further up |

---

## C. Purchase

### purchase_orders
| Column | Type | Notes |
|---|---|---|
| po_no | text unique | PO-2026-0001 |
| request_id | FK→requests | source (approved request) |
| vendor_id | FK→vendors | |
| order_date / expected_date | date | |
| status | enum(open, partially_received, received, closed, canceled) | |
| subtotal / tax / total | money | sales/use tax |

### po_lines
| Column | Type | Notes |
|---|---|---|
| po_id | FK→purchase_orders | |
| product_id | FK→products | |
| qty_ordered / qty_received | numeric | partial-receipt tracking |
| unit_price | money | |
| amount | money | |

---

## D. Inventory — Moving Average

### inbounds (receipts)
| Column | Type | Notes |
|---|---|---|
| inbound_no | text unique | |
| po_id | FK→purchase_orders | |
| received_date | date | |
| status | enum(draft, posted) | posting updates stock and journal entries |

### inbound_lines
| Column | Type | Notes |
|---|---|---|
| inbound_id | FK→inbounds | |
| po_line_id | FK→po_lines | |
| product_id | FK→products | |
| qty_received | numeric | |
| unit_cost | money | receipt unit cost |
| → **Receipt classification branches automatically on product.type** (per line): |
| · type=inventory → received as sellable stock → (Dr) Inventory (Cr) GR/IR |
| · type=asset → received as a fixed asset → create FixedAsset + (Dr) Fixed Asset (Cr) GR/IR |
| · Asset and inventory lines can be mixed on one receipt; each is handled independently |

### outbounds (issues) — symmetric with receipts
| Column | Type | Notes |
|---|---|---|
| outbound_no | text unique | |
| type | enum(sale, consumption, disposal, transfer) | **purpose → auto journal entry branch** |
| issue_date | date | |
| ref_type / ref_id | text/int | source such as a sales order (nullable) |
| memo | text | reason |
| status | enum(draft, posted) | posting deducts stock and creates the journal entry |

### outbound_lines
| Column | Type | Notes |
|---|---|---|
| outbound_id | FK→outbounds | |
| product_id | FK→products | |
| qty | numeric | |
| unit_cost | money | **moving-average cost at issue time** (from stock_balances) |
| inventory_serial_id | FK→inventory_serials | which unit, for serial-tracked items |
| → Auto journal entries by issue type: |
| · sale → (Dr) COGS (Cr) Inventory  *(revenue recognition is handled by the §I AR invoice)* |
| · consumption → (Dr) Expense (department/account) (Cr) Inventory |
| · disposal → (Dr) Inventory Shrinkage Loss (Cr) Inventory |
| · transfer → location move (no accounting impact; multi-warehouse is Phase 2+) |

### stock_movements (stock movement ledger)
| Column | Type | Notes |
|---|---|---|
| product_id | FK→products | |
| movement_type | enum(inbound, outbound, adjustment) | |
| qty | numeric | direction via sign or type |
| unit_cost | money | |
| ref_type / ref_id | text/int | source-document tracing |
| moved_at | timestamp | |

### stock_balances (current stock)
| Column | Type | Notes |
|---|---|---|
| product_id | FK→products PK | one row per item |
| qty_on_hand | numeric | |
| avg_unit_cost | money | **moving average** |
| total_value | money | qty × avg |
| → On receipt: new_avg = (old_qty·old_avg + in_qty·in_cost)/(old_qty+in_qty) |

---

## E. Fixed Assets — Straight-Line

### fixed_assets
| Column | Type | Notes |
|---|---|---|
| asset_no | text unique | |
| name | text | |
| model_name | text | model name |
| serial_number | text | serial number (asset management and tracking) |
| source_inbound_line_id | FK→inbound_lines | source (nullable) |
| acquisition_cost | money | acquisition cost |
| acquisition_date | date | |
| useful_life_months | int | useful life |
| salvage_value | money | salvage value |
| accumulated_depreciation | money | accumulated depreciation |
| status | enum(in_use, disposed) | |
| asset_account_id / accum_account_id / expense_account_id | FK→accounts | for journal entries |

### depreciation_entries
| Column | Type | Notes |
|---|---|---|
| asset_id | FK→fixed_assets | |
| period | text (YYYY-MM) | |
| amount | money | (cost − salvage) / useful life |
| journal_entry_id | FK→journal_entries | link to the auto journal entry |

---

## E-2. Inventory ↔ Asset Conversion (Reclassification)

Convert between sellable inventory and fixed assets in both directions. **Journal entries are made precisely at book value.**

### reclassifications
| Column | Type | Notes |
|---|---|---|
| reclass_no | text unique | |
| type | enum(inventory_to_asset, asset_to_inventory) | direction |
| reclass_date | date | |
| product_id | FK→products | |
| qty | numeric | usually 1 (a serialized unit) |
| inventory_serial_id | FK→inventory_serials | for serial-tracked items |
| fixed_asset_id | FK→fixed_assets | the asset created or converted |
| amount | money | conversion basis amount (below) |
| journal_entry_id | FK→journal_entries | auto journal entry |
| memo | text | reason |

**Conversion accounting:**

```
(1) Inventory → Asset (company puts a sellable item into its own use)
   Basis = moving-average unit cost at issue time
   Deduct stock + create FixedAsset (acquisition cost = basis; model name/serial carried over)
   (Dr) Fixed Asset        (Cr) Inventory

(2) Asset → Inventory (decide to sell an asset in use)
   Basis = book value (NBV) = acquisition cost − accumulated depreciation
   Set FixedAsset status=disposed, receive into stock at NBV unit cost (feeds the moving average)
   (Dr) Inventory          (Cr) Fixed Asset (acquisition cost)
   (Dr) Accumulated Depreciation   ← offsets the accumulated balance
```

> For serial-tracked items, the same unit's model_name/serial_number follows it across the inventory ↔ asset boundary on conversion.

## F. Accounting — Double-Entry

### journal_entries
| Column | Type | Notes |
|---|---|---|
| je_no | text unique | JE-2026-0001 |
| entry_date | date | |
| description | text | memo line |
| source_type | enum(inbound, outbound, asset, reclass, ap_bill, payment, ar_invoice, receipt, expense, bank, depreciation, manual) | automatic/manual origin |
| source_id | int | source document |
| status | enum(draft, posted, reversed) | |
| posted_at | timestamp | |
| reverses_id | FK→journal_entries | the original entry this one reverses (nullable) |
| reversed_by_id | FK→journal_entries | the entry that reversed this one (nullable) |
| → Posted entries cannot be deleted or edited; **corrections happen only via reversal** (POLICIES §G9). Closed periods are locked |

### journal_lines
| Column | Type | Notes |
|---|---|---|
| je_id | FK→journal_entries | |
| account_id | FK→accounts | |
| debit / credit | money | **invariant: Σ debit = Σ credit** |
| memo | text | |

### ap_bills (vendor invoices = accounts payable) — the center of 3-way match
| Column | Type | Notes |
|---|---|---|
| bill_no | text unique | internally numbered |
| vendor_invoice_no | text | the invoice number the vendor provided |
| vendor_id | FK→vendors | |
| po_id | FK→purchase_orders | nullable |
| bill_date / due_date | date | due date computed from payment_terms |
| amount / balance | money | |
| match_status | enum(unmatched, matched, exception) | **result of the PO ↔ receipt ↔ invoice comparison** |
| source | enum(manual, ai_parsed) | whether AI generated it from a PDF |
| attachment_path | text | original invoice PDF |
| status | enum(draft, open, partially_paid, paid) | |
| journal_entry_id | FK→journal_entries | |

### ap_bill_lines (invoice lines matched to receipt lines)
| Column | Type | Notes |
|---|---|---|
| ap_bill_id | FK→ap_bills | |
| inbound_line_id | FK→inbound_lines | match target (nullable) |
| description | text | |
| qty / unit_price / amount | numeric/money | |

### payments (disbursements) + payment_applications
| payments | vendor_id, payment_date, amount, method enum(check, ach, card, wire), bank_account_id |
| payment_applications | payment_id FK, ap_bill_id FK, applied_amount — one payment can be allocated across multiple bills |

---

## G. State Transitions + Auto Journal Entries (Summary)

3-way match is journaled precisely through a **GR/IR (Goods Received/Invoice Received) clearing account**:

```
Request(draft)→submitted→[approval_lines generated by approval rules]
  → all steps approved → Request(approved) → PurchaseOrder(open) auto-created

PO(open) → Inbound(posted)               ← (1) goods arrive (Goods Received)
  → stock_movements(+), stock_balances updated (moving average)
  → JournalEntry:  (Dr) Inventory       (Cr) GR/IR clearing
  → if product.type=asset, create FixedAsset + (Dr) Fixed Asset (Cr) GR/IR

AP Bill (invoice received, manual/AI) → 3-way match against PO and receipt  ← (2) invoice arrives (Invoice Received)
  → posted when match_status = matched
  → JournalEntry:  (Dr) GR/IR clearing  (Cr) AP   (+ variance account if there is a difference)

Payment(posted) → payment_applications → reduces AP Bill balance   ← (3) payment
  → JournalEntry:  (Dr) AP   (Cr) Cash

Outbound(posted) → stock_movements(−), stock_balances reduced (at moving-average cost)
  → JournalEntry (by type):  (Dr) COGS/Expense/Shrinkage Loss   (Cr) Inventory

Reclassification(posted) → inventory ↔ asset conversion
  → inv→asset: (Dr) Fixed Asset (Cr) Inventory
  → asset→inv: (Dr) Inventory + (Dr) Accumulated Depreciation (Cr) Fixed Asset

Month-end Depreciation run → depreciation_entries
  → JournalEntry:  (Dr) Depreciation Expense   (Cr) Accumulated Depreciation

── Sales (AR) side ──────────────────────────
SO(open) → Outbound(sale, posted)        ← goods go out
  → (Dr) COGS (Cr) Inventory  (cost side)
AR Invoice(posted) → bill the customer   ← revenue recognition
  → (Dr) AR (Cr) Revenue (+ (Cr) Sales Tax Payable)
Receipt(posted) → receipt_applications   ← cash collection
  → (Dr) Bank/Cash (Cr) AR

── Expense/reimbursement side ───────────────
Expense Request(approved) → employee reimbursement liability
  → (Dr) Expense (per-category account) (Cr) Employee Payable
Reimbursement Payment(posted)
  → (Dr) Employee Payable (Cr) Cash

── Bank reconciliation ──────────────────────
Bank statement upload → AI extracts line descriptions → statement_lines
  → auto-match against existing journal entries (payments/receipts)
  → unmatched items (bank fees, interest, etc.) create a new JE: (Dr/Cr) relevant account (Cr/Dr) Bank
```

> The GR/IR clearing account **absorbs the timing gap** between the receipt and the invoice. Once both are processed, the GR/IR balance is 0. Un-invoiced or un-received amounts remain as a balance and stay traceable.

---

## H. Accounting Periods & Reports (QuickBooks replacement)

### accounting_periods (accounting periods / close)
| Column | Type | Notes |
|---|---|---|
| period | text (YYYY-MM) | monthly |
| status | enum(open, closed) | **closing locks journal-entry edits for that period** |
| closed_at / closed_by | timestamp/FK | |
| → "Close January" = set the January period to closed. Later entries go only into subsequent periods |

### Reports (not separate tables — "tools" derived from journal entries)
Generated dynamically from double-entry journal lines (journal_lines). **Humans use menus, AI uses conversation** — both call the same functions:
- **Balance Sheet (BS)**
- **Income Statement (IS / P&L)**
- **Cash Flow (CF)**
- **Trial Balance (TB)**
- **General Ledger detail** — per-account ledger
- **AP Aging**
- **Inventory valuation**
- e.g. AI: *"Give me the January close package"* → calls `generate_financials(period='2026-01')` → returns BS+IS

## I. Sales / AR — Mirror of the Purchasing Side

### customers — symmetric with vendors
| Column | Type | Notes |
|---|---|---|
| name / customer_no | text | |
| billing_address / contact | text | |
| payment_terms | text | net30, etc. |
| ar_account_id | FK→accounts | default AR account |

### sales_orders (SO) + so_lines — symmetric with purchase_orders
| sales_orders | so_no, customer_id, order_date, status enum(draft, approved, open, shipped, invoiced, closed) |
| so_lines | so_id, product_id, qty_ordered/qty_shipped, unit_price, amount |
> The issue (Outbound type=sale) links to the SO as its ref → drives the cost (COGS) side journal entry.

### ar_invoices (customer invoices = accounts receivable) + ar_invoice_lines — symmetric with ap_bills
| Column | Type | Notes |
|---|---|---|
| invoice_no | text unique | |
| customer_id | FK→customers | |
| so_id | FK→sales_orders | nullable |
| invoice_date / due_date | date | |
| subtotal / tax_amount / total / balance | money | |
| tax_code_id | FK→tax_codes | **sales tax** |
| status | enum(draft, open, partially_paid, paid) | |
| journal_entry_id | FK→journal_entries | (Dr) AR (Cr) Revenue + (Cr) Sales Tax Payable |
| ar_invoice_lines | ar_invoice_id, product_id, description, qty, unit_price, amount |

### receipts (cash collection) + receipt_applications — symmetric with payments
| receipts | customer_id, receipt_date, amount, method, bank_account_id |
| receipt_applications | receipt_id FK, ar_invoice_id FK, applied_amount — one receipt can be allocated across multiple invoices |
> (Dr) Bank/Cash (Cr) AR. The **AR Aging** report is derived from ar_invoices.balance + due_date.

---

## J. Bank / Cash — Monthly Statement Upload Reconciliation

> No live bank feeds (fully local). **Monthly statement upload → AI extracts line descriptions → reconcile against existing journal entries.**
>
> **Why the upload approach:** QuickBooks-style live feeds go through an **aggregator (Plaid/Yodlee/MX) = a cloud intermediary**, not direct bank APIs → bank credentials must be handed to a third party → conflicts with the "your data never leaves" selling point. The upload approach is **bank-agnostic and fully local**, which makes it the right answer for this product. (OFX/QFX/CSV files are also supported. Plaid only as an optional cloud add-on.)

### bank_accounts
| Column | Type | Notes |
|---|---|---|
| name | text | "Chase operating account" |
| account_no_masked | text | |
| gl_account_id | FK→accounts | linked cash GL account |
| currency | text | USD |

### bank_statements (one row per upload)
| Column | Type | Notes |
|---|---|---|
| bank_account_id | FK→bank_accounts | |
| period | text (YYYY-MM) | |
| opening_balance / closing_balance | money | for reconciliation verification |
| source_file_path | text | uploaded original (PDF/CSV) |
| status | enum(uploaded, parsed, reconciled) | |

### bank_statement_lines (descriptions extracted by AI)
| Column | Type | Notes |
|---|---|---|
| statement_id | FK→bank_statements | |
| txn_date | date | |
| description | text | **line description (AI-parsed)** |
| amount | money | + deposit / − withdrawal |
| matched_journal_line_id | FK→journal_lines | matched journal line (nullable) |
| match_status | enum(unmatched, matched, new_je) | |
| → unmatched: AI proposes candidates or suggests creating a new JE (fees, interest, etc.) |

---

## K. Expense / Reimbursement — Non-PO Spend and Employee Reimbursement

> The endpoint for **spend without a PO**, such as business-trip requests. Approval → employee reimbursement liability → payment.
>
> Note: **Consistency decision (consistency review):** expenses also **reuse the §B `requests` workflow** (`requests.type=expense/trip` + approval via `approval_lines`). No separate `approvals` table or second approval engine. `expense_requests` below is an **expense-specific extension of `requests`** (1:1 link) holding only expense-specific attributes: reimbursee, settlement status, journal entry, etc.

### expense_requests (expense extension of requests — 1:1)
| Column | Type | Notes |
|---|---|---|
| request_id | FK→requests (unique) | **reuses the §B request/approval workflow** (no separate approvals table) |
| employee_id | FK→employees | requester (= reimbursee) |
| expense_type | enum(travel, reimbursement, advance) | |
| status | enum(draft, submitted, approved, rejected, reimbursed) | kept in sync with requests.status, plus the reimbursed stage |
| journal_entry_id | FK→journal_entries | on approval: (Dr) Expense (Cr) Employee Payable |
| → Approval chain, amounts, and title live in requests/request_lines/approval_lines; only expense-specific attributes live here |

### expense_lines
| Column | Type | Notes |
|---|---|---|
| expense_request_id | FK→expense_requests | |
| expense_date | date | |
| category_id | FK→expense_categories | → maps to expense accounts via posting rules |
| description | text | |
| amount | money | |
| attachment_path | text | receipt (AI-parseable) |

> Reimbursement payments reuse §F payments (payee=employee). (Dr) Employee Payable (Cr) Cash.
> Pre-approval (estimated amount before a trip) and settlement (actual receipts) live in the same table, distinguished by status.

---

## K2. Document Intake & Classification (the backbone of RAG and security — DESIGN §8.4)

### documents (single registry for every incoming file)
| Column | Type | Notes |
|---|---|---|
| file_path | text | original storage path |
| filename / mime | text | |
| category_id | FK→document_categories | **AI classification** (invoice/statement/receipt/contract/payroll...) |
| acl_scope | enum(hr, finance, inventory, …, general) | **ACL domain** (DESIGN §8.5 (1)) |
| acl_level | int (1~3) | **ACL grade** ((2)). e.g. payroll=(hr,3) → search-gate filter |
| subject_employee_id | FK→employees | subject employee ((3) boundary check, nullable) |
| extracted_text | text | OCR/extraction (source for RAG indexing) |
| linked_type / linked_id | text/int | linked entity (vendor, customer, employee, period, ...) |
| classified_by | enum(ai, human) | |
| confidence | numeric | if low → (4) gating (ask back) |
| status | enum(quarantined, classified, needs_review, routed, rejected) | **quarantine → promotion flow** |
| is_indexed | bool | **defaults to false. Only promoted, official records get RAG-indexed** (Default-Not-Indexed, §8.6) |
| relevance | enum(business, uncategorized) | failed business-category mapping = uncategorized → no indexing or routing |
| → **Default-Deny: when sensitivity is uncertain, start at the most restrictive grade** and relax only after human confirmation |
| → §8.6 input gate: nothing enters live data/RAG before passing classification and validation. Irrelevant/unanswered → purge |

### document_categories (configuration-type — admin manages categories and rules)
| Column | Type | Notes |
|---|---|---|
| name | text | invoice/bank_statement/receipt/contract/payroll... |
| default_sensitivity | enum | default ACL for this category |
| route_to | text | workflow to trigger (ap_draft/reconcile/expense...) |
| requires_human_review | bool | true for payroll, contracts, etc. |

### document_chunks (RAG vector index — pgvector)
| Column | Type | Notes |
|---|---|---|
| document_id | FK→documents | |
| chunk_text | text | |
| embedding | vector | pgvector |
| acl_scope / acl_level / subject_employee_id | — | **document ACL replicated → enforced filter in search queries (filter before search)** |
| → RAG search enforces: `WHERE user.level[acl_scope] ≥ acl_level AND subject ∈ user.boundary` |

## L. Onboarding / Migration (for commercial sale — go-to-market milestone)

> Not needed for personal use, which starts from zero. This is the migration capability required **when selling to customers coming off an existing system (QB, etc.)**.

**Components:**
1. **Master data import** — customers/vendors/products/COA from CSV, Excel, or QB exports. **AI assists with column and account mapping.**
2. **Opening balances (cutover)** — enter the trial balance as of the cutover date as a single journal entry against an **Opening Balance Equity** account. (Accounting best practice: verify the account nets to 0 afterwards)
3. **Open transaction seeding** — outstanding ap_bills / outstanding ar_invoices / stock_balances on-hand / fixed_assets (+ accumulated depreciation) at their as-of balances. → aging and financial statements are consistent immediately.
4. **Verification report** — automatically compare the post-migration trial balance against the source.

> Minimize new tables — reuse the existing service APIs/posting so that "import = bulk-creating ordinary transactions". Only the **Opening Balance Equity** account is added to the COA seed.

## Z. D6 — Autonomous Fleet + O2C Fulfillment (implemented)

> `fleet` + `sales` modules. Details in [AGENT-FLEET.md](AGENT-FLEET.md).

### fleet_tasks (autonomous work queue)
| Column | Type | Notes |
|---|---|---|
| source | enum | upload·email·bank_feed·ceo_chat·agent |
| source_ref | text? | document_id / email_id / conversation_id |
| category | text | dispatcher classification result |
| from_role / to_role | enum | dispatcher·revenue·spend·accounting·insight·people·supply·docs·support·ceo·system |
| title | text | one human-readable line |
| payload | json | task data (parsed invoice, instructions, etc.) |
| status | enum | queued·in_progress·needs_approval·bounced·done·failed |
| bounce_count / bounce_reason | int/text | bounces (≥3 → escalate to a human) |
| result | json? | output (draft invoice id, etc.) |
| approval_id | int? | approval link (loose) |
| idempotency_key | text unique? | prevents duplicate creation on loop re-runs |

### quotes / quote_lines (O2C quotes)
| quotes | Type | Notes |
|---|---|---|
| quote_no | text unique | QUO-YYYY-NNNN |
| customer_id | FK→customers | |
| quote_date / valid_until | date | |
| status | enum | draft·sent·accepted·rejected·expired |
| customer_po | text? | entered on acceptance |
| so_id | FK→sales_orders? | order created on acceptance |
| subtotal / tax_amount / total | money | |
| **quote_lines** | | quote_id, product_id?, description, qty, unit_price, amount |

### shipments / shipment_lines (shipping / packing list)
| shipments | Type | Notes |
|---|---|---|
| shipment_no | text unique | SHP-YYYY-NNNN |
| so_id | FK→sales_orders | |
| customer_id | FK→customers | |
| ship_date / carrier / tracking_no | date/text | |
| **shipment_lines** | | shipment_id, product_id?, description, qty (product lines deduct stock) |

> O2C flow: quote → send → acceptance (PO) → order → shipment (packing list, stock issue) → invoice (revenue recognition). Each step offers an xlsx document download.

## Settled Modeling Decisions (Q1·Q3·Q5)
- **Decided — Q1: Receiving is a separate document (Inbound).** Supports partial receipts, inspection, and proper accounting.
- **Decided — Q3: 3-way match (PO ↔ receipt ↔ vendor invoice).** AP is created when the invoice arrives (manual/AI). Uses GR/IR clearing.
- **Decided — Q5: Seed the QuickBooks US small-business default COA.** **Strategic goal: this system ultimately replaces QuickBooks** → grow the accounting module into a complete set of books (GL/AP/AR/financial statements/bank reconciliation/1099).

## Settled Decisions (Q2·Q4·Q6)
- **Decided — Q2: Org-chart-based routing is the default**; exceptions are **configured ad hoc by an admin** (fixed_role/fixed_employee routing in approval_rules).
- **Decided — Q4: Single currency, USD.** No multi-currency.
- **Decided — Q6: Financial statements/reports are required** (BS/IS/CF/TB/GL detail/AP aging/inventory valuation). Derived dynamically from journal entries, **callable by AI in conversation** (e.g. "the January close package"). Includes the accounting-period (close) concept.

## 2026-07 Schema Additions (chat P2P completion + agent architecture)

**New tables**
- `user_memories` — cross-conversation user preferences (user_id FK, fact ≤400, source, created_at). Written only through an audited tool. (ADR-6)
- `learned_rules` — governance-learned rules (kind, params JSON, evidence ≤400, status active|revoked, **applied_count**, approved_at). v1 kind=`vendor_alias`. (ADR-10)

**Columns added to existing tables**
- `request_lines.product_url` (≤1000) · `request_lines.price_source` ("user"|"url") — link-based purchase requests; approver double-check.
- `ap_bills.match_note` (≤400) — reason the 3-way match passed or excepted.
- `documents.uploaded_by` (FK users) — resolves "attach the file I just uploaded".

**Behavior changes (schema-related)**
- `inbounds.po_id`/`inbound_lines.po_line_id` are now actually populated (PO-based receiving) → the `InboundPosted` event carries PO info → rolls up `po_lines.qty_received` + transitions PO status.
- The full `purchase_orders` lifecycle is live: draft→open(issue)→partially_received→received(→closed/canceled).
- Alembic: `8b3f2a91c4d7` (the 4 new columns) · `c41d7e55a9b2` (user_memories·learned_rules).

## 2026-07-28 Schema Additions (operations wave: leave · contracts · budget)

**leave module**
- `pto_balances` — days GRANTED per (employee_id FK, year): allowance_days, carried_over_days (Numeric 5,1). Used/pending are always **derived from leave_requests**, never stored (no drift).
- `leave_requests` — employee_id FK, kind (vacation|sick|unpaid), start/end_date, days (business days, weekends excluded), reason ≤400, status (pending|approved|denied|canceled), approver_employee_id FK (immediate manager at request time; NULL = top of org chart → auto-approved with that stated in decision_comment), decided_by_user_id FK, decided_at, decision_comment ≤400. Only `vacation` is balance-gated.
- `onboarding_tasks` — new-hire checklist: employee_id FK, title, doc_category (offer_letter|i9|w4|direct_deposit|handbook_ack), done, done_at, document_id FK (the collected document).

**contracts module**
- `contracts` — the commitments register: title, counterparty, kind (subscription|lease|insurance|service|other), start/end_date, **auto_renew**, **notice_days** (alert window before end_date, default 30), amount + billing (monthly|quarterly|annual|one_time), vendor_id FK?, document_id FK? (the signed PDF), status (active|ended), notes ≤1000. Inside-window contracts surface via `upcoming_renewals` and a weekly INSIGHT inbox card (idempotency key = week + due-set, so a newly due contract re-alerts the same week).

**budget module**
- `budgets` — one row per (account_id FK→accounts, year): monthly_amount. Expense accounts only. Actuals are always **derived from posted journal_lines** (debits − credits in period), never stored. Overruns raise a monthly INSIGHT inbox card (key = month + over-set); `budget_vs_actual` also lists **unbudgeted** expense activity so spend can't hide by omission.

- Alembic: `d92c4f7b1e03` (leave) · `f3a8d21c6b57` (contracts) · `b7e2c94a1f60` (budgets).
