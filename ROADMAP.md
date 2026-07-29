# Roadmap

> Forward-looking only. What's already built is in
> [CURRENT_STATUS.md](CURRENT_STATUS.md); the phase-by-phase build history that
> got us here is preserved in [docs/archive/BUILD-HISTORY.md](docs/archive/BUILD-HISTORY.md).

## Next (reference-architecture scope)

1. **Email inbound** — the highest-value missing intake: poll a mailbox,
   classify attachments with the existing pipeline, and land vendor invoices
   in the approval inbox minutes after they arrive. The fleet's
   `TaskSource.EMAIL` seam already exists.
2. **Risk-sorted approval inbox** — mitigate approval fatigue: rank cards by
   amount, vendor novelty, match status, and budget impact instead of
   chronology.
3. **Evaluation harness** — versioned eval dataset + regression scoring for
   tool selection and figure fidelity, so a model swap is a measured decision.
4. **Dashboards** — spend, cash, and pipeline cards on the landing page
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
customer data migration tooling, per-industry accounting rule packs,
connector credentials/integrations, and production evaluation datasets.
