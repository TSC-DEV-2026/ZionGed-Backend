# from _future_ import annotations
import os, base64, hmac, hashlib
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_MINUTES = int(os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 30)))


_ALG = "pbkdf2_sha256"
_ITER = 200_000
_SALT_LEN = 16

def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("utf-8"))

def hash_password(password: str) -> str:
    if not isinstance(password, str) or password == "":
        raise ValueError("password vazio")
    salt = os.urandom(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)
    return f"{_ALG}${_ITER}${_b64e(salt)}${_b64e(dk)}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        alg, it, salt_b64, hash_b64 = hashed.split("$", 3)
        if alg != _ALG:
            return False
        it = int(it)
        salt = _b64d(salt_b64)
        hv = _b64d(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, it)
        return hmac.compare_digest(dk, hv)
    except Exception:
        return False

def create_access_token(subject: str | int, expires_delta: Optional[timedelta] = None) -> str:
    """
    Gera um JWT de acesso curto, com claim "tipo" = "access".
    """
    to_encode = {
        "sub": str(subject),
        "tipo": "access",
    }
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: str | int, expires_delta: Optional[timedelta] = None) -> str:
    """
    Gera um JWT de refresh, com claim "tipo" = "refresh" e duração maior.
    """
    to_encode = {
        "sub": str(subject),
        "tipo": "refresh",
    }
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)