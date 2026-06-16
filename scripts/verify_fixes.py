"""Live end-to-end check that the A/C hardening holds with the real model.
A: a price-less purchase request must come back as a DRAFT (not auto-submitted).
C: Korean prompts that used to drift to Chinese must reply in Korean."""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.ai import agent
from app.modules.ai.agent import _has_chinese


def main():
    s = SessionLocal()
    user = s.scalars(select(User).where(User.email == "admin@001.local")).first()

    print("=== A: hallucination / draft-first ===")
    out = agent.run(s, user, "사무실용 모니터 3대 구매 요청 올려줘")
    tools = [t["tool"] for t in out["tool_calls"]]
    statuses = [t["result"].get("result", {}).get("status") for t in out["tool_calls"]
                if isinstance(t["result"].get("result"), dict)]
    print("  tools:", tools, "statuses:", statuses)
    print("  no auto-approve:", "approved" not in statuses)
    print("  reply:", out["reply"][:160])

    print("\n=== C: language drift (was Chinese) ===")
    for prompt in ["거래처 담당자한테 결제 늦어 미안하다고 이메일 보내줘",
                   "우리 현금 잔고 원화로 환산하면 얼마야?"]:
        out = agent.run(s, user, prompt)
        print(f"  Q: {prompt}")
        print(f"  KO-only: {not _has_chinese(out['reply'])} | {out['reply'][:140]}")
    s.close()


if __name__ == "__main__":
    main()
