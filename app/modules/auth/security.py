"""Password hashing (bcrypt directly — passlib is unmaintained vs bcrypt 5)."""
import bcrypt

# bcrypt operates on the first 72 bytes; truncate explicitly (bcrypt 5 raises otherwise).
_MAX = 72


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8")[:_MAX], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:_MAX], hashed.encode("utf-8"))
    except ValueError:
        return False
