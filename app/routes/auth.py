# app/routes/auth.py

import os
import re
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models import Pessoa, Usuario, TokenBlacklist
from app.schemas.auth import RegisterIn, RegisterOut
from app.security.password import (
    hash_password,
    verify_password,
)
from app.utils.jwt_handler import criar_token, verificar_token, decode_token

router = APIRouter()

# --- Config de cookies no estilo do outro projeto ---

load_dotenv()
is_prod = os.getenv("ENVIRONMENT") == "prod"

cookie_domain = "ziondocs.com.br" if is_prod else None

cookie_env = {
    "secure": True if is_prod else False,
    "samesite": "Lax",
    "domain": cookie_domain,
}

# --- Registro (igual você já tinha) ---


@router.post(
    "/register",
    response_model=RegisterOut,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    # validações básicas
    if db.scalar(select(Usuario.id).where(Usuario.email == payload.usuario.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já cadastrado",
        )
    if payload.pessoa.cpf and db.scalar(
        select(Pessoa.id).where(Pessoa.cpf == payload.pessoa.cpf)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CPF já cadastrado",
        )

    # cria Pessoa
    pessoa = Pessoa(
        nome=payload.pessoa.nome,
        cpf=payload.pessoa.cpf,
        data_nascimento=payload.pessoa.data_nascimento,
        telefone=payload.pessoa.telefone,
    )
    db.add(pessoa)
    db.flush()

    # cria Usuário vinculado à pessoa (senha hash)
    usuario = Usuario(
        pessoa_id=pessoa.id,
        email=payload.usuario.email,
        senha_hash=hash_password(payload.usuario.senha),
    )
    db.add(usuario)
    db.commit()
    db.refresh(pessoa)
    db.refresh(usuario)

    return RegisterOut(pessoa=pessoa, usuario=usuario)


# --- Login no estilo do outro projeto, com cookies access/refresh ---


class LoginInput(BaseModel):
    # igual ao outro projeto: "usuario" (email ou CPF) + "senha"
    usuario: str
    senha: str


@router.post(
    "/login",
    response_model=None,
    status_code=status.HTTP_200_OK,
)
def login_user(
    payload: LoginInput,
    db: Session = Depends(get_db),
):
    # helper para distinguir e-mail vs CPF
    def is_email(valor: str) -> bool:
        return re.match(r"[^@]+@[^@]+\.[^@]+", valor) is not None

    # busca por e-mail ou CPF
    if is_email(payload.usuario):
        usuario = db.query(Usuario).filter(Usuario.email == payload.usuario).first()
    else:
        pessoa = db.query(Pessoa).filter(Pessoa.cpf == payload.usuario).first()
        if not pessoa:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

        # aqui uso o campo pessoa_id (como no register)
        usuario = (
            db.query(Usuario)
            .filter(Usuario.pessoa_id == pessoa.id)
            .first()
        )

    # valida usuário + senha (usando hash)
    if not usuario or not verify_password(payload.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    # geração dos tokens
    # importante: aqui usamos id = Usuario.id (PK), igual ao /me
    access_token = criar_token(
        {"id": usuario.id, "sub": usuario.email, "tipo": "access"},
        expires_in=60 * 24 * 7,  # 7 dias
    )
    refresh_token = criar_token(
        {"id": usuario.id, "sub": usuario.email, "tipo": "refresh"},
        expires_in=60 * 24 * 30,  # 30 dias
    )

    # monta a resposta com cookies
    response = JSONResponse(content={"message": "Login com sucesso"})
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


# --- /me lendo access_token do cookie ---


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

    # aqui estamos usando o PRÓPRIO token como jti (simples)
    if db.scalar(
        select(TokenBlacklist.id).where(TokenBlacklist.jti == access_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado ou inválido",
        )

    # agora pegamos SOMENTE o "id" do payload (Usuario.id)
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
        "pessoa": {
            "id": user.pessoa.id if user.pessoa else None,
            "nome": user.pessoa.nome if user.pessoa else None,
            "cpf": user.pessoa.cpf if user.pessoa else None,
        },
    }


# --- refresh: usa SÓ o cookie refresh_token ---


@router.post("/refresh")
def refresh_token(request: Request, db: Session = Depends(get_db)):
    # LOGS para debug (igual ao outro projeto)
    print("[REFRESH] Cookies recebidos:", dict(request.cookies))
    print("[REFRESH] Authorization:", request.headers.get("authorization"))

    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="refreshToken não fornecido")

    payload = verificar_token(token)
    if not payload or payload.get("tipo") != "refresh":
        raise HTTPException(status_code=401, detail="refreshToken inválido ou expirado")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido")

    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # aqui é importante manter o mesmo padrão de "id" do access token:
    novo_auth = criar_token(
        {"id": usuario.id, "sub": usuario.email, "tipo": "access"},
        expires_in=60 * 24 * 7,
    )

    response = JSONResponse(content={"message": "Token renovado"})
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



# --- logout: grava na blacklist e apaga cookies ---


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    access_token = request.cookies.get("access_token")
    if access_token:
        try:
            payload = decode_token(access_token)
            if payload:
                # usamos o próprio token como jti (simples)
                db.add(TokenBlacklist(jti=access_token))
                db.commit()
        except Exception as e:
            print(f"[ERRO LOGOUT] {e}")
    else:
        print("[LOGOUT] Token não enviado")

    delete_kwargs = {"path": "/"}
    if cookie_domain:
        delete_kwargs["domain"] = cookie_domain

    response.delete_cookie("access_token", **delete_kwargs)
    response.delete_cookie("refresh_token", **delete_kwargs)
    response.delete_cookie("logged_user", **delete_kwargs)

    return {"message": "Logout realizado com sucesso"}
