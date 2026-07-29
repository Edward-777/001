# 001 — AI Agent Layer Design (D5)

> Design-time document, kept because code comments cite its section numbers.
> For the implemented state see [CURRENT_STATUS.md](../CURRENT_STATUS.md).

> Sections 8.1–8.6 cover AI governance (learning, autonomy, permissions, classification, input gateway). This document covers **how the agent actually runs** — model, tools, loop, RAG.

---

## 1. Local model selection — swappable + two tiers for dev/production

**Principle: never pin the model; keep it swappable.** With Ollama (OpenAI-compatible API), swapping models = one line of config. Country of origin and size class are chosen per deployment.

> **Fully local = country of origin is irrelevant to data leakage.** Open weights are just weight files; when run locally, nothing goes back to the maker (no internet required). Country of origin is a *customer perception/bias* issue, not a *data risk* issue.

**Candidate models:**
| Model | Origin | License | Notes |
|---|---|---|---|
| Qwen2.5 (14B/32B/72B) | Alibaba (China) | Apache 2.0 | **Best-in-class tool calling** for its size |
| **Llama 3.3 70B** | Meta (US) | Open (community) | US-made, strong, **good perception in the US market** |
| Mistral/Mixtral | Mistral (France) | Apache 2.0 | EU-made |
| Gemma 2 | Google (US) | Open | US-made, lightweight |

**Two-tier strategy (our situation):**
- **Development (RTX 4090 / 24GB):** fast prototyping on Qwen2.5-14B or 32B.
- **Production (high-end server sold with the product):** **70B class (Llama 3.3 70B or Qwen2.5-72B)** -> **speed and quality at the same time**, and it also eases the 30-user concurrency concern. "Speed vs. quality" is a 4090-only trade-off; on a strong server you get both.
- **Recommended default (US commercial):** Llama 3.3 70B (US-made, balanced) / Qwen as an option when tool calling matters most.

**Common:**
- **Embeddings (RAG):** bge-m3 or nomic-embed-text — local, multilingual (Korean/English).
- **Runtime:** start with Ollama -> move to vLLM as concurrency grows (see section 6).
- **D5 strategy (decided): don't hard-pin the model — make "per-deployment choice" a product feature.** As a single-tenant appliance, each customer can choose their model (impossible if we were SaaS).
  - Development (4090): **Qwen** (secures the best agentic behavior).
  - Shipping: **Llama 3.3 70B (safe default for the security-sensitive) + Qwen2.5-72B (performance)** — both bundled, chosen at install time (onboarding wizard).
  - Target customers are mixed/undecided -> this "bundle both + choose" approach is optimal. Validate each against benchmarks using our actual toolset.

## 2. Tool Registry

- Each module's `tools.py` registers its own tools -> the `ai` module collects them -> a single registry.
- **Tool schemas = auto-generated from service function signatures + Pydantic DTOs** (always in sync with the code). No hand-written JSON.
- Per-tool metadata: `name, description, params(JSON schema), required_scope` (section 8.5).
- **Permission filtering:** at runtime, only the tools **the current user is allowed to use** are presented to the LLM (first line of defense). At execution time, the service checks **again** (second line, defense in depth).

```
inventory.tools -> [post_inbound, get_stock, ...]
accounting.tools -> [generate_financials, match_ap_bill, ...]   --+
hr.tools, approval.tools, sales.tools, expense.tools, bank.tools --+-> Registry
                                                                   -> filter by user scope -> provided to LLM
```

## 3. Agent loop (orchestration)

```
User message (+ identity and scopes)
 |
 v (1) Build context
   - RAG search (document_chunks with permission filters from sections 8.3 and 8.5 applied)
   - Recent conversation + related entity data (fetched via tools)
 v (2) LLM call (permission-filtered tool list provided)
   +--(a) uncertain -> clarifying question -> ask the user back (section 8.2)
   +--(b) tool call -> execute service (permissions re-checked) -> feed result back -> loop to (2)
   +--(c) final answer
 v (3) Wrap-up
   - Every tool call recorded in audit_logs
   - Posting-type actions follow the section 8.2 autonomy policy (auto-post / confirm when uncertain)
   - Loop cap (max N) -> runaway prevention
```
- **Key point:** tool execution always goes through `service.py` -> the permission gate also fires at execution time (we never trust the tool-list filter alone).
- The LLM never writes journal entries "in prose" -> it **calls the validated posting tool** (the posting engine of section 4). Accounting integrity is guaranteed by code.

## 4. RAG behavior

- **Indexing (sections 8.4 and 8.6):** promoted documents only -> chunking -> local embeddings -> `document_chunks` (pgvector) + ACL tags.
- **Retrieval:** embed the query -> vector search **+ permission-filter SQL** (`user.level[scope] >= acl_level AND subject IN boundary`) -> top-k -> context.
- **Hybrid:** vector + keyword in parallel (exact matching of numbers, IDs, amounts).
- **Facts come from RAG/tools, never from memorization** (section 8.1): questions like "today's inventory" are answered not by RAG but by a **live DB query through a tool**.

## 5. Workflow execution example — "I'm traveling May 1–15" (endgame)

```
User: "I'm going to a conference in Korea May 1-15"
 -> Agent: identifies missing information -> asks back (section 8.2): "Estimated expenses? Flights/lodging included?"
 -> User answers
 -> expense.submit_expense(...) tool call -> expense request draft created
 -> approval.submit_request(...) -> hr.get_approval_chain(requester) derives the approval chain from the org chart automatically
 -> notifications + SSE push to approvers
 -> approval complete -> requester notified + (on approval) automatic journal entry (section 8.2)
```
-> Even without a human filling out a form, **natural language -> tool sequence** produces the same result. The tools are the hands and feet.

## 6. Concurrency / capacity (honest limits)

- If 30 people generate AI output *simultaneously* on a single 4090, requests **queue**. Most people don't use AI at the same moment, but plan for peaks.
- Mitigations: **vLLM** (continuous batching) for throughput, or split inference onto a **separate server (the server-business box)**.
- ERP transactions (forms, lists) are fast independent of the LLM — only AI responses slow down.
- Open decision: assume a peak concurrent-AI-user count -> Ollama vs. vLLM, whether to split inference out.

## 6.5 Model upgrades / retuning — "what if a better model comes out?"

**Not starting from scratch.** The real asset is not the tuned adapter but the **training dataset**.

- LoRA adapters are base-model-bound (a Qwen adapter cannot attach to Llama) -> adapters are byproducts.
- **The data flywheel is the permanent asset:** training dataset (interaction logs + human corrections) + RAG corpus + eval set. The model is the **substrate** you swap out on top of it.

**Three layers when swapping models:**
| Layer | Retraining | Notes |
|---|---|---|
| RAG / tools / DB | **Zero** | Fully model-agnostic. The new model queries the same data. Most of the company knowledge |
| Behavior LoRA | **Re-run (automated)** | Retrain on the archived dataset against the new base. A few hours, scripted |
| Eval | Re-run | Validate new model + adapter; deploy on pass, roll back otherwise |

- This is where section 8.1 ("facts = RAG, behavior = tuning") shines: the big chunk (facts) costs zero on a model swap; only the lightweight behavior tuning is re-run.
- **Design principle:** version-control the training dataset and eval set **like code**. An upgrade = the "point at new base -> retrain -> pass eval -> deploy" pipeline.
- Bonus: the smarter the base, the **less tuning it needs**. A great new model release is good news.

**What a model swap *improves* (= what the base provides) vs. what *stays the same*:**
| Improves (engine/brain) | Stays the same (knowledge/assets) |
|---|---|
| Reasoning (decomposing complex requests) | Company facts, documents, DB (RAG) |
| **Tool-calling accuracy** (our lifeline) | Behavior dataset |
| Instruction following, fewer hallucinations | Tools, prompts, schemas |
| Language quality, long-context use | |
| (Newer models) image understanding -> better section 8.4 classification | |
> Analogy: **hiring a smarter employee** — the books, policies, and operating manuals (data) stay the same; only that person's *understanding, reasoning, and accuracy* go up. Re-onboard with the same manual (re-run tuning). A model upgrade raises the "working brain," not a "re-education of company knowledge."

## 6.6 Agent scope — work-only by default + general-assistant option

"Our company's own LLM" = three layers: general-purpose base + company behavior tuning + company data (RAG). **Because the foundation is a general-purpose model, coding and general questions are possible in terms of capability** — whether it *should* do them is product policy (scope).

**Decided: default = work-only; admin can toggle general-assistant mode (per deployment).**
- **Scope is enforced at the prompt/policy layer** (not capability removal -> no retuning needed, reversible):
  - System-prompt persona: "You are the ERP assistant for Company X. You support accounting, inventory, and approvals. Politely redirect unrelated requests."
  - Optional lightweight intent guard to detect off-topic requests.
- **Default (work-only):** politely decline/redirect off-topic and coding requests. Saves compute, protects quality, keeps the identity clear.
- **General-assistant mode (admin ON):** coding and general questions allowed. However:
  - Company data still goes through the permission gate (section 8.5).
  - General answers have **no RAG grounding -> explicitly labeled "general knowledge, not company-verified"** (liability management).
  - ERP work tasks take compute priority (general questions must not block work).
  - All usage is audit-logged.

## 7. Guardrail summary (all tied back to existing sections)

| Risk | Defense | Source |
|---|---|---|
| Leakage beyond permissions | Tool-list filter + re-check at execution + RAG ACL | Sections 8.3, 8.5 |
| Wrong automatic handling | Uncertainty gating (asking back) + weekly/monthly audits | Section 8.2 |
| Broken accounting | LLM never writes journal entries directly; posting tools only | Section 4 |
| Noise / contamination | Input gateway (quarantined, unindexed) | Section 8.6 |
| Prompt injection | Documents = data (not commands), sandboxing, permission gate stays on | Section 8.6 |
| Runaway loops | Loop cap + audit logs | This document |

## 8. Shipped agent architecture extensions (2026-07-24 · design rationale = docs/ADR.md)

- **Plan-then-Execute (`ai/planner.py` + `agent.run`):** known intents (month-end close) use **template plans** (deterministic); only other multi-action requests that pass the gate trigger a single planning call. Each step runs through the same permission-checked tool loop; a failed step skips the remainder and the failure is stated in the answer. **Maker-checker state spans the entire turn (all plan steps)** — a plan cannot create a draft and submit it in one turn. Rendered in chat as a ✓/✗/– checklist. (ADR-5)
- **Cross-conversation memory (`ai/memory.py`, `user_memories`):** only preferences the user states explicitly are recorded, via an audited tool (`remember_preference`) — no implicit extraction by the model. Injected into the system prompt every turn, capped at 30 entries, deletable by keyword. (ADR-6)
- **Governance learning loop (`learning` module + `fleet/miner.py`):** a deterministic miner extracts patterns from recorded human decisions -> rule **proposal cards** on `/fleet` -> active on approval (+ side effect: deactivates duplicate vendors) -> `procurement.resolve_vendor` is applied across every lookup path -> utility measured via `applied_count`. Rejections are remembered and never re-proposed. v1 rule: vendor aliases (duplicate-vendor resolution). (ADR-10)
- **Honesty backstop (`agent.py`):** failed tool calls (at both the registry and handler level) get `action_failed` + a "report the failure" instruction stamped into the result data — deterministically blocks the observed "claim success after failure" cases. Marked with ⚠ in the timeline. (ADR-3)
- **Execution timeline:** below every answer, per-tool ✓/⚠ + elapsed ms — execution transparency as the UI default.
