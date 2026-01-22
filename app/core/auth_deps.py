# app/core/auth_deps.py

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import jwt, JWTError  # <- use jose, não "jwt" puro
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select

from app.database.connection import get_db  # <- nome correto
from app.models.auth import Usuario

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
COOKIE_CANDIDATES = ("session.xaccess", "access_token", "token")


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    for name in COOKIE_CANDIDATES:
        val = request.cookies.get(name)
        if val:
            if isinstance(val, str) and val.lower().startswith("bearer "):
                return val.split(" ", 1)[1].strip()
            return val
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Usuario:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub") or payload.get("user_id") or payload.get("uid")
        uid = int(sub)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.execute(
        select(Usuario).options(joinedload(Usuario.pessoa)).where(Usuario.id == uid)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
