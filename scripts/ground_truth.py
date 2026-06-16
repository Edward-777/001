"""Print exact tool outputs so the hard benchmark can check figure fidelity."""
import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.ai import tools_builtin as T


def main():
    s = SessionLocal()
    u = s.scalars(select(User).where(User.email == "admin@001.local")).first()
    probes = {
        "ap_aging": (T._get_ap_aging, {}),
        "ar_aging": (T._get_ar_aging, {}),
        "runway": (T._get_runway, {}),
        "income_2025": (T._get_income_statement, {"year": 2025}),
        "vendors": (T._list_vendors, {}),
        "open_bills": (T._list_open_bills, {}),
    }
    for name, (fn, args) in probes.items():
        try:
            out = fn(s, u, args)
            print(f"### {name}({args})\n{json.dumps(out, ensure_ascii=False, default=str)[:600]}\n")
        except Exception as e:
            print(f"### {name} -> EXC {type(e).__name__}: {e}\n")
    s.close()


if __name__ == "__main__":
    main()
