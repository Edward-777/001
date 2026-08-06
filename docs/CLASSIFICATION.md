# Document Classification — taxonomy, and the rubric for growing it

> Why the classifier has exactly seven categories, what each one triggers,
> and the decision rubric + priority list for expanding the taxonomy when
> email intake is re-attached. Code: `app/modules/ai/classify.py`.

## Today's taxonomy (7 classes)

One vision-model call (or a CSV heuristic / text-model call) yields a single
category, and that category drives BOTH the document's ACL and its workflow:

| Category | ACL | Route | RAG |
|---|---|---|---|
| invoice | finance L2 | vision-parse → fleet draft bill | – |
| bank_statement | finance L2 | parse → auto-reconcile | – |
| receipt | finance L1 | expense | – |
| packing_list | inventory L2 | fleet draft goods receipt | – |
| policy | general L1 | chunk + index | ✓ |
| contract | finance L3 | store | – |
| other *(default-deny)* | **finance L3 (most restrictive)** | store, never indexed | – |

## The rubric — when a new category earns its place

A class is added ONLY when at least one holds:

1. **Misclassification is dangerous** — the wrong automation would run.
2. **The ACL must differ** — the default assignment exposes the document to
   the wrong audience.
3. **Downstream automation exists** — a route that actually does something.

Everything else falls into `other`, which is safe by construction (most
restrictive ACL, no automation, no indexing). Classes are not free: the
classifier is a small local vision model answering with one word, and its
accuracy degrades as the label set grows — every addition must pay rent.

## Known gaps, in risk order (deferred to email re-attach)

1. **`vendor_statement`** — a vendor's month-end list of open invoices looks
   like an invoice; classified as one, it drafts DUPLICATE bills. The most
   common real-world AP intake failure. Route: HELD/store, finance L2. *(Rubric #1.)*
2. **`credit_memo`** — a vendor credit reads as an invoice and would draft a
   POSITIVE bill for money that flows the other way. Route: store + human
   card. *(Rubric #1.)*
3. **Direction confusion — `customer_po` / `remittance_advice`** — the
   current taxonomy is purchase-side only; customer money documents
   misclassify as invoices and draft payables. O2C automation already exists
   to route to. *(Rubric #1 + #3.)*
4. **`hr_document`** — resumes, offers, I-9/W-4 land in `other` → finance L3,
   which is the WRONG SCOPE: finance readers see personnel files. Needs hr
   scope + per-subject data boundary. *(Rubric #2.)*
5. **`tax_notice`** — IRS/state notices can propose compliance-calendar cards
   now that the obligations module exists. *(Rubric #3.)*

Not worth a class yet (safe in `other`, low volume, no automation): W-9s
(handled by the attach-to-vendor flow), certificates of insurance, BOLs,
vendor quotes.

## The better structural move: two-stage classification

Rather than growing one flat label set, keep stage 1 coarse (what kind of
document) and add stage 2 ONLY for money documents: *"is this billing US, a
statement OF our account, or FROM our customer?"* — one extra question that
resolves gaps 1–3 without inflating the label set stage 1 must discriminate.

## Measurement gate (non-negotiable)

No taxonomy change ships without a **classification battery** first — the
EVAL.md pattern applied here: N sample documents per category × 3 runs,
scored deterministically, so the accuracy cost of every new label is measured
before it's trusted. Adding classes without this is flying blind on the exact
component whose mistakes route money documents.
