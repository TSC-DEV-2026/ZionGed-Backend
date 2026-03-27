from __future__ import annotations

import os
import re
import secrets
import string
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models import Pessoa, Usuario, TokenBlacklist
from app.schemas.auth import RegisterIn, RegisterOut, LoginInput, LoginExecutavelInput
from app.security.password import hash_password, verify_password
from app.utils.jwt_handler import criar_token, verificar_token, decode_token

router = APIRouter()

load_dotenv()
is_prod = os.getenv("ENVIRONMENT") == "prod"

cookie_domain = "ziondocs.com.br" if is_prod else None

cookie_env = {
    "secure": True if is_prod else False,
    "samesite": "Lax",
    "domain": cookie_domain,
}


def normalizar_cpf(cpf: str | None) -> str | None:
    if not cpf:
        return None
    digits = re.sub(r"\D", "", cpf)
    return digits or None


def gerar_login_token(db: Session) -> str:
    chars = string.ascii_letters + string.digits

    while True:
        token = "".join(secrets.choice(chars) for _ in range(20))
        existe = db.scalar(select(Pessoa.id).where(Pessoa.login_token == token))
        if not existe:
            return token


def montar_resposta_login(usuario: Usuario) -> JSONResponse:
    access_token = criar_token(
        {"id": usuario.id, "sub": usuario.email, "tipo": "access"},
        expires_in=60 * 24 * 7,
    )
    refresh_token = criar_token(
        {"id": usuario.id, "sub": usuario.email, "tipo": "refresh"},
        expires_in=60 * 24 * 30,
    )

    response = JSONResponse(
        content={
            "message": "Login com sucesso",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "usuario": {
                "id": usuario.id,
                "email": usuario.email,
                "is_active": usuario.is_active,
                "last_login_at": usuario.last_login_at.isoformat() if usuario.last_login_at else None,
                "pessoa": {
                    "id": usuario.pessoa.id if usuario.pessoa else None,
                    "nome": usuario.pessoa.nome if usuario.pessoa else None,
                    "cpf": usuario.pessoa.cpf if usuario.pessoa else None,
                    "telefone": usuario.pessoa.telefone if usuario.pessoa else None,
                    "login_token": usuario.pessoa.login_token if usuario.pessoa else None,
                },
            },
        }
    )

    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        path="/",
        **cookie_env,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        max_age=60 * 60 * 24 * 30,
        path="/",
        **cookie_env,
    )
    response.set_cookie(
        "logged_user",
        "true",
        httponly=False,
        max_age=60 * 60 * 24 * 7,
        path="/",
        **cookie_env,
    )

    return response


@router.post(
    "/register",
    response_model=RegisterOut,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    cpf_normalizado = normalizar_cpf(payload.pessoa.cpf)

    if db.scalar(select(Usuario.id).where(Usuario.email == payload.usuario.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já cadastrado",
        )

    if cpf_normalizado and db.scalar(select(Pessoa.id).where(Pessoa.cpf == cpf_normalizado)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CPF já cadastrado",
        )

    pessoa = Pessoa(
        nome=payload.pessoa.nome,
        cpf=cpf_normalizado,
        data_nascimento=payload.pessoa.data_nascimento,
        telefone=payload.pessoa.telefone,
        login_token=gerar_login_token(db),
    )
    db.add(pessoa)
    db.flush()

    usuario = Usuario(
        pessoa_id=pessoa.id,
        email=payload.usuario.email,
        senha_hash=hash_password(payload.usuario.senha),
        is_active=True,
    )
    db.add(usuario)
    db.commit()
    db.refresh(pessoa)
    db.refresh(usuario)

    return RegisterOut(pessoa=pessoa, usuario=usuario)


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
)
def login_user(payload: LoginInput, db: Session = Depends(get_db)):
    valor_login = payload.usuario.strip()

    def is_email(valor: str) -> bool:
        return re.match(r"[^@]+@[^@]+\.[^@]+", valor) is not None

    if is_email(valor_login):
        usuario = (
            db.query(Usuario)
            .options(joinedload(Usuario.pessoa))
            .filter(Usuario.email == valor_login)
            .first()
        )
    else:
        cpf_normalizado = normalizar_cpf(valor_login)
        pessoa = db.query(Pessoa).filter(Pessoa.cpf == cpf_normalizado).first()
        if not pessoa:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

        usuario = (
            db.query(Usuario)
            .options(joinedload(Usuario.pessoa))
            .filter(Usuario.pessoa_id == pessoa.id)
            .first()
        )

    if not usuario or not verify_password(payload.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    if not usuario.is_active:
        raise HTTPException(status_code=403, detail="Usuário inativo")

    usuario.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(usuario)

    return montar_resposta_login(usuario)


@router.post(
    "/login-executavel",
    status_code=status.HTTP_200_OK,
)
def login_executavel(payload: LoginExecutavelInput, db: Session = Depends(get_db)):
    token = payload.token.strip()

    usuario = (
        db.query(Usuario)
        .join(Pessoa, Pessoa.id == Usuario.pessoa_id)
        .options(joinedload(Usuario.pessoa))
        .filter(Pessoa.login_token == token)
        .first()
    )

    if not usuario:
        raise HTTPException(status_code=401, detail="Token de login inválido")

    if not usuario.is_active:
        raise HTTPException(status_code=403, detail="Usuário inativo")

    usuario.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(usuario)

    return montar_resposta_login(usuario)


@router.get("/me")
def get_me(request: Request, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação ausente",
        )

    payload = verificar_token(access_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )

    if db.scalar(select(TokenBlacklist.id).where(TokenBlacklist.jti == jti)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado ou inválido",
        )

    uid = payload.get("id")
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )

    try:
        uid = int(uid)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )

    user = db.execute(
        select(Usuario)
        .options(joinedload(Usuario.pessoa))
        .where(Usuario.id == uid)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado",
        )

    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "pessoa": {
            "id": user.pessoa.id if user.pessoa else None,
            "nome": user.pessoa.nome if user.pessoa else None,
            "cpf": user.pessoa.cpf if user.pessoa else None,
            "telefone": user.pessoa.telefone if user.pessoa else None,
            "login_token": user.pessoa.login_token if user.pessoa else None,
        },
    }


@router.post("/refresh")
def refresh_token(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="refreshToken não fornecido")

    payload = verificar_token(token)
    if not payload or payload.get("tipo") != "refresh":
        raise HTTPException(status_code=401, detail="refreshToken inválido ou expirado")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido")

    usuario = (
        db.query(Usuario)
        .options(joinedload(Usuario.pessoa))
        .filter(Usuario.email == email)
        .first()
    )
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if not usuario.is_active:
        raise HTTPException(status_code=403, detail="Usuário inativo")

    novo_auth = criar_token(
        {"id": usuario.id, "sub": usuario.email, "tipo": "access"},
        expires_in=60 * 24 * 7,
    )

    response = JSONResponse(
        content={
            "message": "Token renovado",
            "access_token": novo_auth,
        }
    )
    response.set_cookie(
        "access_token",
        novo_auth,
        httponly=True,
        path="/",
        max_age=60 * 60 * 24 * 7,
        **cookie_env,
    )
    response.set_cookie(
        "logged_user",
        "true",
        httponly=False,
        path="/",
        max_age=60 * 60 * 24 * 7,
        **cookie_env,
    )

    return response


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")

    if access_token:
        try:
            payload = decode_token(access_token)
            if payload:
                jti = payload.get("jti")
                if jti and not db.scalar(select(TokenBlacklist.id).where(TokenBlacklist.jti == jti)):
                    db.add(TokenBlacklist(jti=jti))
                    db.commit()
        except Exception:
            pass

    delete_kwargs = {"path": "/"}
    if cookie_domain:
        delete_kwargs["domain"] = cookie_domain

    response.delete_cookie("access_token", **delete_kwargs)
    response.delete_cookie("refresh_token", **delete_kwargs)
    response.delete_cookie("logged_user", **delete_kwargs)

    return {"message": "Logout realizado com sucesso"}