# Mail Integration Plan — from the filesystem simulator to real mailboxes

> The public reference implementation ships `FilesystemMailbox` (drop `.eml`
> into `mailbox/inbox/`, sent mail lands in `mailbox/outbox/` stamped
> `SENT_SIMULATED`). This document is the plan for connecting real mailboxes.
> The protocol and every downstream behavior are already final — providers
> are adapters, and they live in the private deployment layer.

## 1. The boundary that already exists

Everything downstream of `MailProvider` is provider-agnostic and shipped:

```
MailProvider.poll() -> [RawEmail]          MailProvider.send(...) -> receipt
        │                                          ▲
        ▼                                          │
 mail.service.ingest()                    mail.service.send_outbound()
   idempotent by Message-ID                 human send gate (draft → sent)
   sender ↔ vendor matching                 audit-logged, single-shot
   provenance default-deny
   fleet dispatch (DRAFTS only)
```

A real integration therefore means implementing exactly two methods per
provider, plus credential handling. Nothing else changes — not the
classification, not the default-deny rules, not the tests.

## 2. Provider adapters (private layer)

| Provider | Inbound | Outbound | Auth | Notes |
|---|---|---|---|---|
| **IMAP/SMTP (generic)** | IMAP IDLE or poll `UNSEEN`; move to a `Processed` folder (mirrors inbox/→processed/) | SMTP submission | app password or OAuth2 SASL | The lowest common denominator; works with any host |
| **Gmail API** | `users.messages.list` with `historyId` cursor; push via Pub/Sub watch | `users.messages.send` | OAuth2 (installed-app or service account w/ domain delegation) | Preferred for Google Workspace tenants |
| **Microsoft Graph** | delta query on the inbox; webhook subscriptions | `sendMail` | OAuth2 client credentials | Preferred for M365 tenants |

Adapter contract details:
- **Idempotency stays message-side**: `ingest()` dedupes on Message-ID, so
  crash-and-repoll is always safe; adapters may deliver duplicates freely.
- **Consume-on-read**: each adapter must implement the equivalent of the
  filesystem move (IMAP folder move, Gmail label swap, Graph
  `isRead`+category) so a poison message cannot wedge the inbox — same
  guarantee `FilesystemMailbox.poll()` gives today.
- **A dedicated operations address** (e.g. `ap@company.com`), not a personal
  inbox — the intake surface is a role, not a person.

## 3. Credentials & security (why this is private-layer)

- Tokens/secrets live in the deployment's secret store, never in the repo,
  never in the database. The reference repo contains no credential fields by
  design.
- **Egress governance**: outbound send is the first real data-egress path in
  the system. The send gate already requires a human; the deployment adds an
  allowlist of recipient domains for L2 sends and logs every send with the
  provider receipt (already stored as `provider_ref`).
- Inbound attachments keep the existing rules: extension allowlist, generated
  filenames, provenance default-deny (statements/policies from email are HELD;
  only draft-producing categories dispatch).
- SPF/DKIM/DMARC verdicts (available in all three providers' metadata) get
  recorded onto `inbound_emails` and become a matching input: a sender that
  fails DMARC never auto-matches a vendor, no matter what the From says.

## 4. Rollout sequence

1. **Read-only shadow** — adapter polls the real mailbox but ingest runs with
   dispatch disabled; humans compare the Mailroom against reality for a week.
2. **Inbound live** — dispatch on (drafts only, as today). The approval inbox
   is the safety net; nothing changed about what email is allowed to do.
3. **Outbound live** — replace `SENT_SIMULATED` with real submission behind
   the same human send gate, recipient-domain allowlist on.
4. **Push instead of poll** — Pub/Sub / Graph webhooks once volumes justify it
   (the poll tick stays as the fallback path).

## 5. What deliberately does NOT change

- Email content remains data, never commands (test-pinned).
- Email can produce **drafts and held items only** — the human approval inbox
  is the sole path from an email to a posted journal.
- The AI still has no send tool; sending remains a human action.
