import base64
import hashlib
import hmac
import secrets

N = 2**14
R = 8
P = 1
SALT_BYTES = 16
KEY_BYTES = 32
MEMORY_LIMIT = 64 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=KEY_BYTES, maxmem=MEMORY_LIMIT)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        derived = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(derived, base64.b64decode(expected))
    except ValueError:
        return False


DUMMY_HASH = hash_password("no-such-user", salt=b"\x00" * SALT_BYTES)
