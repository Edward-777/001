# Roadmap

> Forward-looking only. What's already built is in
> [CURRENT_STATUS.md](CURRENT_STATUS.md); the phase-by-phase build history that
> got us here is preserved in [docs/archive/BUILD-HISTORY.md](docs/archive/BUILD-HISTORY.md).

## Shipped since this roadmap was written

Email intake + maker-checker outbox (the fifth intake surface; real
providers are private-layer — [docs/MAIL-INTEGRATION.md](docs/MAIL-INTEGRATION.md)),
the **autonomy policy engine** (human-signed L3 envelopes, fail-closed,
self-suspending), the **compliance calendar** (self-perpetuating recurring
duties + US reference seed), and **payment instructions** (the system
prepares remit-to + evidence packets; humans execute; confirmation posts).

## Next (reference-architecture scope)

1. **Sourcing (RFQ)** — the front end of procurement: identify qualified
   vendors, request quotes (over the outbox), compare price/delivery/terms/
   history, and feed the winner into the existing PO → receipt → 3-way-match
   spine. Generalizes to external professional services (insurance, legal,
   tax) as engagement matters.
2. **Auditor mode** — time-boxed read-all access grants; evidence-chain
   pulls, GL↔subledger tie-outs, seeded sampling, PBC automation. The audit
   trail, reversal-only ledger, and policy decision records already exist —
   this is the conversational interface over them.
3. **Risk-sorted approval inbox** — mitigate approval fatigue: rank cards by
   amount, vendor novelty, match status, and budget impact instead of
   chronology.
4. **Evaluation depth** — the live-model battery exists
   ([docs/EVAL.md](docs/EVAL.md)); next is paraphrase coverage for the weak
   phrasings it found, new cases for the mail/policy/payments tools, and a
   versioned dataset so a model swap is a measured decision.
   4b. **Classification taxonomy expansion** — gated on email re-attach and on
   a classification battery existing first: vendor statements, credit memos,
   money-document direction (stage-2 check), HR-document ACL, tax notices —
   rubric and priority order in [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md).
5. **Dashboards** — spend, cash, and pipeline cards on the landing page
   (the runtime map at `/map` already covers the AI runtime itself).

## Later

- Field-level close locking and remaining state-transition coverage
- Budget suggestions mined from actuals (learning-loop kind #2:
  per-vendor match tolerance, approval bands)
- Model benchmarking for the shipping default (Llama 70B vs Qwen 72B)

## Deliberately out of public scope

These belong to a deployment/product layer, not the reference architecture
(see [PRODUCT_VISION.md](PRODUCT_VISION.md)):

payroll & tax execution (integrate Gusto/ADP — regulated, don't rebuild),
live bank feeds and payment rails, installer & appliance provisioning,
production data-migration tooling (the source-agnostic migration design stays
public — [docs/MIGRATION.md](docs/MIGRATION.md) — source adapters do not),
per-industry accounting rule packs, provider-specific connector
deployments and credential management (generic intake interfaces stay
public), and production evaluation datasets.
