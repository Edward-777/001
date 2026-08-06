# Architecture Decision Records — 001, an Enterprise AI Operating System

Why the system is built the way it is. Each record: the decision, what was
rejected, and the consequences we accepted — with evidence from the running
system where we have it. (Feature inventory lives in README/OVERVIEW; this
document is only about the *why*.)

---

## ADR-1 · The AI has no privileged execution path

**Decision.** Every module exposes exactly one public entry point (`service.py`).
Human routes, AI tools, and autonomous fleet agents all call the same service
functions. There is no "AI API" beside the app — the AI *is* a caller of the app.

**Rejected alternative.** A dedicated agent backend with its own data access
(faster to build, and what most "AI copilot" retrofits do). Rejected because two
write paths inevitably drift: the AI path skips the validation the human path
gained last sprint, and audits can no longer answer "could the AI have done X?"
by reading one layer.

**Consequences.** Adding any AI capability first means making the *service*
capability exist — which is why tools are thin (~10-line) wrappers. The automated test
suite exercises the same functions the AI calls, so test coverage of the app IS
test coverage of the agent's action space.

---

## ADR-2 · One permission predicate for UI, AI tools, and RAG

**Decision.** A single predicate (`auth.can_access`: scope × level ×
data-boundary, boundary resolved through the HR org chart) gates web routes, is
applied twice to AI tools (tools a user may not call are not even *offered* to
the model; execution re-checks), and filters RAG retrieval per chunk.

**Rejected alternative.** Separate ACL systems per surface (route guards + a
tool allowlist + retrieval filters). Rejected because permission systems that
must agree eventually disagree, and the AI surface is exactly where a gap
becomes an exfiltration channel: a model that can *retrieve* a document its
user can't *open* has already leaked it.

**Consequences.** An employee asking the assistant for the income statement is
refused by the same line of code that returns 403 on `/reports/financials`
(test-pinned: `test_finance_tools_inherit_permissions`,
`test_vendor_tools_hidden_from_plain_employee`). Offering-time filtering also
shrinks the tool catalog per user, which measurably helps a 14B model's tool
selection.

---

## ADR-3 · Guardrails live in code, not prompts

**Decision.** Every control that matters is deterministic: the maker-checker
gate (a draft-creating tool and the submit tool cannot run in the same user
turn — enforced in the agent loop, spanning all plan steps), over-receipt
rejection, 3-way-match exceptions never posting, segregation of duties (bill
entry at finance L2, payment at L3). The system prompt states the rules; the
code makes them unbreakable.

**Evidence, not theory.** During development we recorded the local model
(qwen2.5:14b) doing all of the following in live sessions: inventing a unit
price for a purchase request; claiming a receipt was recorded after the tool
had rejected it (fabricated inbound number); creating unsolicited vendor bills
in a loop. **In every incident the ledger stayed clean** — the fabricated
submit was blocked, the over-receipt refused, the rogue bills quarantined as
match exceptions in draft. The failures that remained were *verbal*: the model
lied about what had happened. So we added a deterministic honesty backstop —
any failed tool call is stamped `action_failed` with an instruction to report
the failure — and re-verified the same scenarios ("only 2 units remain to
receive…" with a warning marker in the visible execution timeline).

**Consequences.** Prompt-rule violations degrade UX, never books. Model
upgrades don't require re-auditing safety, only quality.

---

## ADR-4 · Humans approve; agents only ever draft

**Decision.** Any consequential action — posting to the ledger, paying, issuing
spend, receiving stock — requires a human decision. Autonomous fleet roles
(invoice → bill, packing list → goods receipt, payment runs, month-end close)
produce *drafts* parked in one Approval Inbox; the approver-side effect runs
only on approval. In chat, money requests are created as drafts the user must
confirm in a *later* turn before submission.

**Rejected alternative.** Confidence-thresholded auto-execution ("post if the
model is >90% sure"). Rejected because LLM self-reported confidence is not a
probability, and a finance buyer will ask exactly one question: "what's the
worst thing it can do without a human?" The answer here is: create a draft.

**Consequences.** Throughput is bounded by human attention — mitigated by
making approval cheap (one inbox, cards carrying vendor/amount/PO-match/variance
notes, chat approvals with line items). The product bet: leverage comes from
10× more supervised work per person, not from removing the person.

---

## ADR-5 · Plan deterministically when possible; gate LLM planning

**Decision.** Multi-step requests run plan-then-execute, but planning is layered:
known intents (month-end close) get a *template* plan the LLM only executes;
free-form planning happens behind a cheap deterministic gate (single questions
never pay the extra call); malformed plans degrade to the plain tool loop.
Each step executes through the same permission-checked loop, and the
maker-checker gate spans the whole turn — a plan cannot create a draft in step
1 and submit it in step 2 (test-pinned).

**Rejected alternative.** Always-plan agentic loops (plan → reflect → act per
turn). Rejected for latency (local 14B), and because a planner is one more
component that can hallucinate work the user didn't ask for; template plans
make the most valuable workflows deterministic end-to-end.

---

## ADR-6 · Memory is a table, not an embedding store — and writes are explicit

**Decision.** Cross-conversation memory is a `user_memories` table written only
by an audited tool call when the user states a preference, injected into the
system prompt, capped, deduplicated, and deletable by keyword. Never silently
extracted by the model from conversation.

**Rejected alternative.** Post-turn LLM extraction into a vector store.
Rejected because implicit memory is unauditable (what does the system believe
about me, and why?), grows without consent, and turns a compliance question
into a research problem. A table can be shown to the user; an embedding can't.

---

## ADR-7 · Three small local models, not one large one

**Decision.** Chat (qwen2.5:14b), vision (qwen2.5-vl:7b) and embeddings
(bge-m3) run co-resident on one 24 GB GPU (~17 GB, num_ctx sized so nothing
spills to CPU). Models are per-deployment config, not code.

**Rejected alternative.** One large multimodal model. A 32B-class model alone
fills the card, forces model swapping under memory pressure (measured: silent
CPU fallback is ~20× slower), and couples every capability to one vendor's
release cycle. Specialized small models also fail *independently* — a vision
regression can't break chat.

**Consequences.** The system must assume a *mid-capability* chat model — which
is precisely why ADR-3's code-level guardrails exist. Failure handling is
layered: transient LLM 5xx retried once (VRAM swap window), tool calls emitted
as text recovered by parsing, CJK language drift regenerated once
deterministically, vision misreads caught downstream (unrecognized documents
quarantine at the most restrictive ACL; ambiguous PO matches fail to a human;
mismatched invoices become non-posting exceptions).

---

## ADR-8 · Local single-tenant appliance, not multi-tenant SaaS

**Decision.** Each customer runs the entire system — app, database, all three
models — on their own box. Nothing leaves the machine: invoices are parsed,
policies indexed, and product pages summarized locally (the one outbound call,
fetching a user-supplied product URL, is SSRF-guarded and sends nothing).

**Rejected alternative.** Multi-tenant SaaS with cloud LLM APIs — better
margins, faster iteration. Rejected because the target buyer is handing an AI
its books, payroll, and contracts; "your data trains nobody and travels
nowhere" is the sales argument, and single-tenancy makes tenant-isolation bugs
structurally impossible rather than merely tested-for.

**Consequences.** Ops burden shifts on-prem (mitigations: preflight GPU/model
health checks, nightly backups, Alembic migrations, production boot interlock
that refuses default secrets). Model quality is capped by customer hardware —
see ADR-7's consequence.

---

## ADR-9 · Why back-office accounting first

**Decision.** The first domain an agent operates end-to-end is double-entry
accounting and its physical counterpart (procure-to-pay, order-to-cash).

**Reasoning.** Accounting is the one business domain where an agent's
correctness is *provable*: the books must balance, every action leaves a
journal trail, and independent legs (PO ↔ receipt ↔ invoice) cross-check each
other. When the model misbehaves, the ledger itself is the detector — the
3-way match caught the model's own fabricated bills (ADR-3). A domain with
built-in invariants is the right proving ground for trustworthy agents;
domains with fuzzier ground truth (support, HR) inherit the hardened
machinery afterwards.

---

## ADR-10 · Learning is governed: mined, proposed, approved, measured

**Decision.** The system gets smarter through *learned rules*, not weight drift.
A deterministic miner scans decisions and data the platform already records
(every approval with its reason, every match exception with its cause, every
tool call with its outcome) for repeating patterns. Each pattern becomes a
**proposal card in the same approval inbox** as every other consequential
action. Approval activates the rule; behavior changes on the very next
occurrence; `applied_count` on the rule row measures the payoff. Rejection is
remembered and never re-proposed. Rules are rows — inspectable, revocable.

**First shipped loop (from a real incident).** During development an uploaded
invoice said "Office Depot, Inc." while the master data had "Office Depot"; the
spend agent auto-created a duplicate vendor and the books began splitting
across the two. The miner now detects vendors sharing a normalized name
(punctuation/legal-suffix folding), proposes *"treat 'Office Depot, Inc.' as
'Office Depot' and deactivate the duplicate"*, and — once approved — every
vendor lookup (invoice parsing, packing lists, chat tools) resolves through the
alias. The failure that motivated the rule cannot recur, and the rule row
counts how often it fired.

**Rejected alternative.** Implicit adaptation — fine-tuning on outcomes, or
prompt-injecting recent failures. Rejected for the same reason as ADR-6: an
enterprise must be able to answer *"what has this system learned, who approved
it, and how do we undo it?"* with a table, not a research project. Learning
that cannot be audited is drift.

**Consequences.** Learning velocity is bounded by human approval — deliberate:
each rule is reviewed once and pays off forever after. The miner framework is
kind-extensible (per-vendor match tolerances and approval-band suggestions are
natural next kinds mined from `match_note` and approval histories).

---

## ADR-11 · Measure the model; trust only the gates

**Decision.** The one probabilistic component — the local model — is measured
by a behavior battery (`scripts/battery_tools.py`, results in
[EVAL.md](EVAL.md)) that drives the *real* agent loop and tool registry on a
seeded throwaway world: six axes (tool choice, argument fidelity, permission
refusal, ambiguity→ask, failure honesty, maker-checker), each in Korean and
English, scored deterministically over N runs with no retries. Failures are
published, not massaged: the table shows where a 14B model is weak, alongside
the observation that every weak spot fails *closed*.

**Evidence, not theory.** The battery's first runs caught three defects that
live use had missed: (1) qwen resolved bare dates against its training era —
"8월 24일부터 연차" became `2023-08-24` — even with today's date at the top of
the system prompt (fix: the date rides on the user turn, the tokens the model
actually honors); (2) a Korean budget question drew a fluent **Russian** reply,
sailing past a Chinese-only language backstop (fix: the backstop now catches
any foreign-script drift); (3) asked to order servers with no price, the model
fabricated a product URL and retried the rejected create call to the iteration
limit (fix: a tool failing three times in one turn is withdrawn, forcing the
question the model should have asked). After the fixes, three independent runs
produced identical results — the remaining failures are stable model limits,
not flakiness.

**Rejected alternative.** Trusting the 358 deterministic tests to speak for the
system. They prove the gates; they say nothing about whether the model picks
the right tool for "연차 며칠 남았어?". Conversely, prompt-tuning until every
battery case passes was also rejected — a benchmark you tune to saturation
stops measuring.

**Consequences.** A model swap (the 70B-class shipping benchmark, or any future
upgrade) is a measured decision: re-run the battery, diff the table. Evaluation
data stays out of the public repo (transcripts are gitignored); the method and
the honest summary are public.

---

## ADR-12 · Prompt levers don't hold — remove the pen, not the instruction

**Decision.** When the model misbehaves with a tool, the fix is never another
sentence in a prompt — it is a structural gate that makes the misbehavior
impossible: template plan steps carry **tool allowlists** (a close step
physically cannot call a write tool); the registry **rejects undeclared
argument names** instead of letting handlers silently default them; one failed
money-write tool **freezes every other money-write tool** for the rest of the
turn (the substitution gate); a spend envelope **requires a money bound** at
the service layer; and a failed plan step is **stamped into the reply**
deterministically, above whatever the compose model writes.

**Evidence, not theory (2026-08-04 full-system review, all live).** (1) Inside
the month-close plan, the model registered invented compliance obligations with
2023 dates — *twice*, straight past a "never invent" tool description AND a
"NEVER create" step directive; the step allowlist ended it (3 calls, 9s,
zero writes). (2) It called `generate_report` with invented argument names and
presented the silently-defaulted wrong-month package as the answer; argument
validation turned that into a loud, retryable error. (3) Asked to pay a
nonexistent bill, it failed honestly — then confirmed an *unrelated* prepared
payment instruction with a fabricated bank reference and reported success,
identically across three runs, with the anti-substitution instruction already
in the failure stamp; the substitution gate ended it. (4) Told to require
money bounds, it invented one — but the bound lands in a DRAFT a human must
activate, which is the gate doing its job.

**Rejected alternative.** Iterating on descriptions and directives until the
battery passes. Each incident above already had the right instruction in
place; a 14B model under plan pressure walks through instructions. Gates are
also model-portable: a future model swap inherits them for free.

**Consequences.** New write tools must ship with a gate story, not a
description promise: which allowlists include them, what the registry
validates, whether they join `_MONEY_WRITE_TOOLS`. The battery (ADR-11) is the
regression net that proves each gate held.
