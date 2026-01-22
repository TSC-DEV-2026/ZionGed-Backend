import os
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select

from app.database.connection import get_db
from app.models.auth import Usuario, TokenBlacklist

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
COOKIE_CANDIDATES = ("session.xaccess", "access_token", "token")


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()

    for name in COOKIE_CANDIDATES:
        cookie_val = request.cookies.get(name)
        if cookie_val:
            return cookie_val

    return None


def _invalid_token() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido",
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Usuario:
    token = _extract_token(request)
    if not token:
        _invalid_token()

    blacklisted = db.execute(
        select(TokenBlacklist.id).where(TokenBlacklist.jti == token)
    ).scalar_one_or_none()
    if blacklisted:
        _invalid_token()

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        _invalid_token()
    except Exception:
        _invalid_token()

    uid = payload.get("sub") or payload.get("user_id") or payload.get("uid")
    try:
        uid = int(uid)
    except Exception:
        _invalid_token()

    user = db.execute(
        select(Usuario).options(joinedload(Usuario.pessoa)).where(Usuario.id == uid)
    ).scalar_one_or_none()
    if not user:
        _invalid_token()

    return user


__all__ = ["get_current_user", "_extract_token", "COOKIE_CANDIDATES"]
