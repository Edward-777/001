# AI Ops — local model runtime (sizing & stability)

The product runs three local models on the customer's box via Ollama:

| role   | default model      | ~VRAM | purpose                        |
|--------|--------------------|-------|--------------------------------|
| chat   | `qwen2.5:14b`      | ~10GB | the agent / tool-calling brain |
| vision | `qwen2.5vl:7b`     | ~6GB  | invoice & document parsing     |
| embed  | `bge-m3`           | ~1.2GB| RAG / company-policy search    |

**They must coexist.** The agent, invoice parsing, and policy search are used in the
same session, so all three need to be resident at once. Budget ≈ **17GB**, which fits
a single 24GB GPU (RTX 4090) with headroom for the KV cache (`OLLAMA_NUM_CTX=8192`).

## Why not the 32B chat model?

`qwen2.5:32b` has better tool discipline but needs ~21GB on its own. On a 24GB card
that leaves no room for the embed/vision models: when one of them is requested, Ollama
tries to load it under VRAM pressure, `llama-server` **crashes** (`exit status
0xc0000005`), and Ollama can no longer refresh its free-VRAM accounting — so RAG /
policy search stays broken until Ollama is restarted. Use 32B only on ≥40GB VRAM or a
second GPU. The default is 14B so the full stack is stable on the reference hardware.

## Known issue: GPU discovery crash → silent CPU fallback

On some driver combinations (observed: Ollama 0.30.6 + NVIDIA driver 595.95),
`llama-server --list-devices` crashes with `0xc0000005`. Ollama then disables CUDA and
loads every model on **CPU** — the app still answers, but ~20x slower. `nvidia-smi`
shows the GPU healthy, so the fault is the bundled runtime vs the driver, not hardware.

**Detect it:** `python scripts/preflight_ai.py` — it fails loudly if any model is
running 100% CPU while a GPU is present.

**Remediate (in order):**
1. Restart Ollama cleanly (quit the tray app, then relaunch it — not a bare
   `ollama serve`, which on this setup did not pick up the GPU).
2. Keep models within the VRAM budget above so the load-under-pressure crash that
   poisons GPU discovery never triggers.
3. If it persists, align versions: update Ollama, or roll the NVIDIA driver back to a
   build the bundled `llama-server` supports.

## Resilience built into the app

`app/modules/ai/llm.py` retries once on a transient 5xx / dropped connection (a model
swap can blip on the first hit). A persistent failure surfaces as a normal error the
agent reports gracefully ("couldn't reach the policy search") rather than a crash.
