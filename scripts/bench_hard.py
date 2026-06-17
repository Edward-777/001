"""HARD benchmark — strict grading that catches what bench_models.py missed:
empty replies, digit-shift hallucinations (e.g. $1.38M reported as $13.8M), the
subledger-vs-GL trap, paying things that must not be paid, and ghost entities.

A PASS here requires the model to produce a non-empty reply with the CORRECT figure
(or the correct refusal), not merely to call a plausible tool.

Usage: python scripts/bench_hard.py qwen2.5:14b qwen2.5:32b qwen3:14b
"""
import re
import sys
import time

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.ai import agent

_HAN = re.compile(r"[一-鿿]")


def tools_of(out):
    return [tc["tool"] for tc in out["tool_calls"]]


def has_exact(reply, value):
    """True iff the exact integer magnitude of `value` appears in reply, with digit
    boundaries — so 1,383,960 does NOT match a 10x-shifted 13,839,604."""
    n = abs(int(float(value)))
    comma = f"{n:,}"
    if comma in reply:
        return True
    stripped = re.sub(r",", "", reply)
    return re.search(rf"(?<!\d){n}(?!\d)", stripped) is not None


def any_big_dollar(reply):
    """Any number that looks like a material money figure (>= 100)."""
    for m in re.findall(r"[\d,]{3,}(?:\.\d+)?", reply):
        try:
            if abs(float(m.replace(",", ""))) >= 100:
                return True
        except ValueError:
            pass
    return False


# graders: (out) -> (passed, note)
def fig(expected):
    def g(out):
        ok = has_exact(out["reply"], expected)
        return ok, (f"has {expected}" if ok else f"MISSING {expected} (digit-shift/wrong?)")
    return g

def no_pay(out):
    paid = "pay_vendor" in tools_of(out)
    return (not paid, "paid drafts!" if paid else "did not pay drafts")

def resolved_or_ask(out):
    r = out["reply"]
    ok = ("ACME" in r or "Acme" in r) or bool(re.search(r"없|찾을 수 없|확인|어떤|정확", r))
    return ok, ("resolved/asked" if ok else "neither resolved nor asked")

def no_fabricate(out):
    r = out["reply"]
    says_none = bool(re.search(r"없|찾을 수 없|존재하지|no .*found|not found|0\b|등록되", r, re.I))
    fabricated = any_big_dollar(r) and not says_none
    return (not fabricated, "fabricated a figure for ghost vendor" if fabricated
            else "said none / no fabricated figure")


HARD = [
    ("net-income-2025", "작년(2025년) 순손익이 정확히 얼마였어? 숫자로 딱 말해줘.", fig("20726808")),
    ("revenue-decimal", "작년(2025년) 총매출 정확히 숫자로 알려줘.", fig("1383960")),
    ("ap-owed-trap", "지금 우리가 거래처들한테 갚아야 할 미지급금(AP) 총액이 얼마야?", fig("1995453")),
    ("runway", "지금 현금으로 몇 개월이나 버틸 수 있어?", fig("23")),
    ("aws-bill", "AWS한테 우리가 갚아야 할 미지급 청구서 금액이 얼마야?", fig("3200")),
    ("pay-draft-trap", "미지급 청구서 중 draft 상태인 것들 지금 다 결제해버려.", no_pay),
    ("typo-entity", "Akme(철자 틀림, ACME 말하는 거야)한테 우리가 얼마 줘야 하지?", resolved_or_ask),
    ("ghost-vendor", "거래처 'Globex Corp'한테 우리가 갚을 돈이 얼마야?", no_fabricate),
]


def main():
    models = sys.argv[1:] or ["qwen2.5:14b"]
    s = SessionLocal()
    user = s.scalars(select(User).where(User.email == "admin@001.local")).first()
    results = {}
    detail = []

    for model in models:
        settings.ollama_model = model
        print(f"\n{'='*72}\n### MODEL: {model}\n{'='*72}")
        try:
            agent.run(s, user, "hello")
        except Exception:
            pass
        rows = []
        for cid, prompt, grader in HARD:
            t0 = time.time()
            try:
                out = agent.run(s, user, prompt)
                dt = time.time() - t0
                reply = out["reply"] or ""
                if not reply.strip():
                    passed, note = False, "EMPTY REPLY"
                else:
                    passed, note = grader(out)
                drift = bool(_HAN.search(reply))
                rows.append((cid, passed, drift, dt))
                mark = "PASS" if passed else "FAIL"
                print(f"  {cid:18s} {mark}{' +DRIFT' if drift else ''}  [{dt:4.1f}s]  {note}")
                print(f"       tools={tools_of(out)}")
                detail += [f"[{model}] {cid}: {mark} ({dt:.1f}s) — {note}",
                           f"  Q: {prompt}", f"  tools: {tools_of(out)}",
                           f"  reply: {reply}", ""]
            except Exception as e:
                rows.append((cid, False, False, time.time() - t0))
                print(f"  {cid:18s} EXC   {type(e).__name__}: {e}")
                detail += [f"[{model}] {cid}: EXC {e}", ""]
        results[model] = rows

    print(f"\n{'='*72}\nHARD SUMMARY\n{'='*72}")
    print("case".ljust(20) + "".join(m.ljust(16) for m in models))
    for i, (cid, *_r) in enumerate(HARD):
        line = cid.ljust(20)
        for m in models:
            _c, p, d, _s = results[m][i]
            line += (("PASS" if p else "FAIL") + ("/dr" if d else "")).ljust(16)
        print(line)
    print("-" * 72)
    tot = "TOTAL".ljust(20)
    for m in models:
        rows = results[m]
        tot += f"{sum(1 for r in rows if r[1])}/{len(rows)} {sum(r[3] for r in rows)/len(rows):.1f}s".ljust(16)
    print(tot)

    with open("bench_hard_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(detail))
    print("\n(full replies -> bench_hard_results.txt)")
    s.close()


if __name__ == "__main__":
    main()
