"""Operator preflight for the local AI stack. Run after install / on boot to catch
a degraded runtime BEFORE users hit it — most importantly a silent CPU fallback
(Ollama dropping to CPU when GPU discovery crashes), which leaves the app "working"
but ~20x too slow.

  python scripts/preflight_ai.py

Exit code 0 = healthy, 1 = a check failed. Checks: server reachable, the three
configured models present, and chat + embed both functional. Reports the processor
(GPU vs CPU) each loaded model is running on."""
import sys

import httpx

from app.core.config import settings
from app.modules.ai import llm

BASE = settings.ollama_base_url


def _ok(msg):
    print(f"  [OK]   {msg}")


def _fail(msg):
    print(f"  [FAIL] {msg}")


def main() -> int:
    failures = 0
    print(f"Ollama preflight @ {BASE}")

    # 1. server reachable + which models are installed
    try:
        tags = httpx.get(f"{BASE}/api/tags", timeout=5).json()
        installed = {m["name"].split(":")[0]: m["name"] for m in tags.get("models", [])}
        _ok(f"server reachable — {len(installed)} model(s) installed")
    except Exception as exc:
        _fail(f"server unreachable: {exc}")
        print("\nIs Ollama running?  Start it from the Ollama app, or `ollama serve`.")
        return 1

    # 2. the three configured models are present
    wanted = {"chat": settings.ollama_model, "embed": settings.ollama_embed_model,
              "vision": settings.ollama_vision_model}
    for role, name in wanted.items():
        base = name.split(":")[0]
        if base in installed:
            _ok(f"{role} model present: {name}")
        else:
            _fail(f"{role} model MISSING: {name}  ->  run `ollama pull {name}`")
            failures += 1

    # 3. chat + embed actually run (this is also what loads them into VRAM)
    try:
        r = llm.chat([{"role": "user", "content": "reply with the single word OK"}])
        _ok(f"chat works: {(r.get('content') or '').strip()[:30]!r}")
    except Exception as exc:
        _fail(f"chat failed: {type(exc).__name__}: {exc}")
        failures += 1
    try:
        v = llm.embed("preflight embedding probe")
        _ok(f"embed works: {len(v)}-dim vector")
    except Exception as exc:
        _fail(f"embed failed: {type(exc).__name__}: {exc}  (RAG/policy search will be down)")
        failures += 1

    # 4. processor check — warn loudly on CPU fallback
    try:
        ps = httpx.get(f"{BASE}/api/ps", timeout=5).json()
        for m in ps.get("models", []):
            size_vram = m.get("size_vram", 0)
            total = m.get("size", 1) or 1
            on_gpu = size_vram > 0
            pct = round(100 * size_vram / total)
            tag = f"{pct}% GPU" if on_gpu else "100% CPU"
            (_ok if on_gpu else _fail)(f"{m['name']} running on {tag}")
            if not on_gpu:
                failures += 1
    except Exception as exc:
        print(f"  [warn] could not read /api/ps: {exc}")

    print("\nRESULT:", "HEALTHY" if failures == 0 else f"{failures} CHECK(S) FAILED")
    if failures:
        print("If models report 100% CPU while a GPU exists, Ollama's GPU discovery "
              "likely crashed (see docs/AI-OPS.md) — restart Ollama; if it persists, "
              "the bundled runtime may be incompatible with the installed NVIDIA driver.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
