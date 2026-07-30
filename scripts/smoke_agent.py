"""One-off smoke test: drive the real AI agent against dev.db via live Ollama.
Proves the full path: NL -> LLM (qwen2.5:32b) -> tool call -> service -> answer.
The default prompt is Korean on purpose — the system is bilingual (docs/EVAL.md)."""
import sys
import time

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.ai import agent
from sqlalchemy import select


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "지금 우리 회사 현금 잔고가 얼마야?"
    s = SessionLocal()
    user = s.scalars(select(User).where(User.email == "admin@001.local")).first()
    print(f"[user] {user.name} <{user.email}> role={user.role}")
    print(f"[ask ] {msg}\n")
    t0 = time.time()
    out = agent.run(s, user, msg)
    dt = time.time() - t0
    print("=== TOOL CALLS ===")
    for tc in out["tool_calls"]:
        print(f"  -> {tc['tool']}({tc['args']})")
        print(f"     = {str(tc['result'])[:200]}")
    print("\n=== REPLY ===")
    print(out["reply"])
    print(f"\n[took {dt:.1f}s, {len(out['tool_calls'])} tool call(s)]")
    s.close()


if __name__ == "__main__":
    main()
