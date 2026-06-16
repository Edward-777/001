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

**Ollama 0.30.x (observed 0.30.6 / 0.30.8) ships a new GPU-discovery path that spawns
`llama-server --list-devices`, and on this machine it crashes with `0xc0000005` for
*every* backend (cuda_v12, cuda_v13, rocm, vulkan alike).** Ollama then disables the GPU
and loads every model on **CPU** — the app still answers, but ~20x slower. `nvidia-smi`
shows the GPU healthy, so the fault is the bundled `llama-server` discovery binary, not
the driver or hardware.

This is **deterministic, not transient**: it survives a full process kill, an Ollama
force-reinstall, *and* a reboot. (The reason 0.30.8 appears to work right after install
is a cached discovery result; once that's invalidated, live re-discovery crashes and it
falls to CPU for good.)

**Detect it:** `python scripts/preflight_ai.py` — it fails loudly if any model is
running 100% CPU while a GPU is present. Or check the server log for
`failure during llama-server GPU discovery ... 0xc0000005`.

**Fix (confirmed working on the reference box — RTX 4090, driver 595.95):** pin Ollama
to **0.24.0**, which uses the older, robust GPU discovery (no `--list-devices` probe):

```powershell
winget install --id Ollama.Ollama -e --version 0.24.0 --force --scope user
[Environment]::SetEnvironmentVariable("OLLAMA_NO_UPDATE","1","User")   # stop auto-update back to 0.30.x
```

After this, a bare `ollama serve` picks up the GPU fine (`ollama ps` → `100% GPU`).
**Do not let the tray app auto-update past 0.24.x** until a 0.30.x build fixes the
discovery crash — `OLLAMA_NO_UPDATE=1` is what holds the pin.

Independently, keep models within the VRAM budget above (default chat = 14B, not 32B) so
a load-under-pressure crash never compounds the problem.

## Resilience built into the app

`app/modules/ai/llm.py` retries once on a transient 5xx / dropped connection (a model
swap can blip on the first hit). A persistent failure surfaces as a normal error the
agent reports gracefully ("couldn't reach the policy search") rather than a crash.
